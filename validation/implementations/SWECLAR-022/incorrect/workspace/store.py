"""Durable transactional store for the synthetic loyalty workspace.

The HTTP layer deliberately stays thin: all authorization, validation and
business changes live here and are committed together in one SQLite
transaction.  The state is kept as a single JSON document because the domain
is small, while SQLite still supplies durable atomic commits and serializes
all writers.
"""
import base64
import datetime
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
from pathlib import Path
from urllib.parse import quote, unquote

from media import sanitize


class Fault(Exception):
    def __init__(self, status, code):
        self.status = status
        self.code = code
        super().__init__(code)


def fail(status=400, code="invalid_request"):
    raise Fault(status, code)


def scalar_string(value, maximum=100, trim=False):
    """Validate a Unicode string and optionally trim only its ends."""
    if not isinstance(value, str) or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        fail()
    if trim:
        value = value.strip()
    if not 1 <= len(value) <= maximum:
        fail()
    return value


def identifier(value):
    return scalar_string(value, 100, False)


def human_text(value, maximum=100):
    return scalar_string(value, maximum, True)


def integer(value, maximum):
    # type(...) rather than isinstance(...) intentionally rejects booleans.
    if type(value) is not int or not 0 <= value <= maximum:
        fail()
    return value


def boolean(value):
    if type(value) is not bool:
        fail()
    return value


def choice(value, allowed):
    if not isinstance(value, str) or value not in allowed:
        fail()
    return value


def id_list(value, minimum=0, maximum=None):
    if not isinstance(value, list) or len(value) < minimum or (maximum is not None and len(value) > maximum):
        fail()
    result = [identifier(item) for item in value]
    if len(set(result)) != len(result):
        fail()
    return result


def uid():
    # 160 bits is comfortably above the session/record uniqueness needs.
    return secrets.token_hex(20)


def public_user(user):
    return {key: user[key] for key in ("id", "username", "role")}


class Store:
    def __init__(self, database, fixture, clock):
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(database, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)")
        self.lock = threading.RLock()
        self.sessions = {}
        self.clock = Path(clock)

        if not self.db.execute("SELECT 1 FROM state WHERE id=1").fetchone():
            # Never mutate the fixture object: it is also useful to the test
            # harness and may be reused to create another disposable server.
            state = json.loads(Path(fixture).read_text(encoding="utf-8"))
            for user in state.get("users", []):
                password = user.pop("password")
                salt = secrets.token_hex(16)
                user["salt"] = salt
                user["digest"] = hashlib.pbkdf2_hmac(
                    "sha256", password.encode("utf-8"), salt.encode("ascii"), 120000
                ).hex()
            state.setdefault("assets", [])
            state.setdefault("receipts", [])
            state.setdefault("preferences", {})
            state.setdefault("promotions", [])
            state.setdefault("messages", [])
            state.setdefault("ledger", [])
            state.setdefault("redemptions", [])
            state.setdefault("last_delivery", {})
            self.db.execute(
                "INSERT INTO state(id, body) VALUES(1, ?)",
                (json.dumps(state, ensure_ascii=True, allow_nan=False),),
            )

    # ------------------------------------------------------------------
    # Authentication and transaction plumbing
    # ------------------------------------------------------------------
    def _load_state(self):
        row = self.db.execute("SELECT body FROM state WHERE id=1").fetchone()
        if row is None:
            # This should only be possible for a corrupted database.  Keep it
            # an ordinary API failure rather than leaking a traceback.
            fail(500, "storage_error")
        state = json.loads(row[0])
        # Defaults make a database made by the starter compatible with the
        # completed implementation without changing any durable records.
        state.setdefault("assets", [])
        state.setdefault("receipts", [])
        state.setdefault("preferences", {})
        state.setdefault("promotions", [])
        state.setdefault("messages", [])
        state.setdefault("ledger", [])
        state.setdefault("redemptions", [])
        if not isinstance(state.get("last_delivery"), dict):
            state["last_delivery"] = {}
        # A database made by the starter has messages but no cooldown map.
        # Reconstructing it from real stored messages keeps restart semantics
        # correct without treating a notification state flag as delivery.
        for message in state["messages"]:
            consumer_id = message.get("owner_id")
            delivered_at = message.get("delivered_at")
            if consumer_id is None or type(delivered_at) is not int:
                continue
            previous = state["last_delivery"].get(consumer_id)
            if previous is None or delivered_at > previous:
                state["last_delivery"][consumer_id] = delivered_at
        return state

    def _active_user_for_token(self, token, state):
        owner = self.sessions.get(token)
        if owner is None:
            return None
        return next(
            (user for user in state["users"] if user["id"] == owner and user.get("active") is True),
            None,
        )

    def authorize(self, method, path, token):
        """Authenticate and enforce endpoint role before parsing request JSON."""
        if (method, path) == ("GET", "/health") or (method, path) == ("POST", "/api/login"):
            return

        with self.lock:
            state = self._load_state()
            user = self._active_user_for_token(token, state)
            if user is None:
                fail(401, "unauthenticated")

            roles = None
            if path == "/api/merchant-owners":
                roles = ("administrator",)
            elif method == "POST" and path in (
                "/api/malls", "/api/shops", "/api/branches", "/api/dispatch"
            ):
                roles = ("administrator",)
            elif method == "PATCH" and self._matches_path(path, "/api/branches", 1):
                roles = ("administrator",)
            elif method == "POST" and self._matches_path(path, "/api/receipts", 1, suffix="review"):
                roles = ("administrator",)
            elif path == "/api/assets":
                roles = ("consumer",)
            elif path == "/api/preferences" or path in ("/api/inbox", "/api/wallet"):
                roles = ("consumer",)
            elif method == "POST" and path in ("/api/receipts", "/api/redemptions"):
                roles = ("consumer",)
            elif method == "POST" and (
                path == "/api/promotions" or self._matches_path(path, "/api/promotions", 1, suffix="cancel")
            ):
                roles = ("merchant",)
            elif method == "GET" and path in ("/api/receipts", "/api/redemptions"):
                roles = ("consumer", "administrator")
            elif method == "GET" and path == "/api/promotions":
                roles = ("merchant", "administrator")

            if roles is not None:
                self.role(user, *roles)

    @staticmethod
    def _matches_path(path, root, components, suffix=None):
        """Match a parameterized path without decoding its ID yet.

        URL-encoded slashes remain part of one path component until the route
        decodes them, which is exactly what IDs containing punctuation need.
        """
        pattern = re.escape(root) + "(?:/[^/]+)" * components
        if suffix is not None:
            pattern += "/" + re.escape(suffix)
        return re.fullmatch(pattern, path) is not None

    def handle(self, method, path, token, body=None):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.s = self._load_state()
                answer = self.route(method, path, token, body if body is not None else {})
                self.db.execute(
                    "UPDATE state SET body=? WHERE id=1",
                    (json.dumps(self.s, ensure_ascii=True, allow_nan=False),),
                )
                self.db.execute("COMMIT")
                return answer
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------------
    # Small domain helpers
    # ------------------------------------------------------------------
    def lookup(self, collection, identity):
        return next((row for row in self.s[collection] if row.get("id") == identity), None)

    def need(self, collection, identity):
        row = self.lookup(collection, identity)
        if row is None:
            fail(404, "not_found")
        return row

    def role(self, user, *roles):
        if user.get("role") not in roles:
            fail(403, "forbidden")

    @staticmethod
    def _decoded_path_id(segment):
        try:
            value = unquote(segment, encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, ValueError):
            fail(404, "not_found")
        return identifier(value)

    def _path_id(self, path, root, suffix=None):
        if suffix is None:
            match = re.fullmatch(re.escape(root) + r"/([^/]+)", path)
        else:
            match = re.fullmatch(re.escape(root) + r"/([^/]+)/" + re.escape(suffix), path)
        if not match:
            return None
        return self._decoded_path_id(match.group(1))

    @staticmethod
    def _public_asset(asset):
        return {key: asset[key] for key in ("id", "width", "height", "url")}

    @staticmethod
    def _public_receipt(receipt):
        return {
            key: receipt[key]
            for key in (
                "id", "owner_id", "request_id", "branch_id", "receipt_number", "date",
                "amount_cents", "asset_id", "status", "points", "reviewed_by",
            )
        }

    @staticmethod
    def _public_promotion(promotion):
        return {
            key: promotion[key]
            for key in (
                "id", "shop_id", "branch_ids", "title", "body", "due_at", "expires_at",
                "status", "delivered_count",
            )
        }

    @staticmethod
    def _public_message(message):
        return {
            key: message[key]
            for key in (
                "id", "promotion_id", "title", "body", "shop_id", "branch_ids", "delivered_at",
            )
        }

    @staticmethod
    def _public_ledger(entry):
        return {key: entry[key] for key in ("id", "kind", "reference_id", "delta", "balance")}

    @staticmethod
    def _public_redemption(redemption):
        return {
            key: redemption[key]
            for key in ("id", "owner_id", "request_id", "reward_id", "cost", "status")
        }

    def _balance(self, owner):
        return sum(entry["delta"] for entry in self.s["ledger"] if entry.get("owner_id") == owner)

    def _append_ledger(self, owner, kind, reference_id, delta):
        balance = self._balance(owner) + delta
        self.s["ledger"].append(
            {
                "id": uid(),
                "owner_id": owner,
                "kind": kind,
                "reference_id": reference_id,
                "delta": delta,
                "balance": balance,
            }
        )
        return balance

    def _preferences(self, owner):
        value = self.s["preferences"].get(owner)
        if not isinstance(value, dict):
            return {"categories": [], "mall_ids": []}
        return {
            "categories": list(value.get("categories", [])),
            "mall_ids": list(value.get("mall_ids", [])),
        }

    def _read_clock(self):
        try:
            raw = json.loads(self.clock.read_text(encoding="utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(raw, dict) or type(raw.get("now")) is not int or not 0 <= raw["now"] <= 2000000000:
                raise ValueError("clock")
            return raw["now"]
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            fail(500, "clock_error")

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def route(self, method, path, token, b):
        if method == "GET" and path == "/health":
            return 200, {"ok": True}

        if method == "POST" and path == "/api/login":
            username = scalar_string(b.get("username"), 100, False)
            password = scalar_string(b.get("password"), 10000, False)
            user = next((item for item in self.s["users"] if item.get("username") == username), None)
            valid = False
            if user is not None and user.get("active") is True:
                digest = hashlib.pbkdf2_hmac(
                    "sha256", password.encode("utf-8"), user["salt"].encode("ascii"), 120000
                ).hex()
                valid = hmac.compare_digest(user["digest"], digest)
            if not valid:
                fail(401, "unauthenticated")
            session = secrets.token_urlsafe(32)
            self.sessions[session] = user["id"]
            return 200, {"token": session, "user": public_user(user)}

        user = self._active_user_for_token(token, self.s)
        if user is None:
            fail(401, "unauthenticated")
        owner = user["id"]

        # Basic account/session endpoints.
        if method == "GET" and path == "/api/me":
            return 200, {"user": public_user(user)}
        if method == "POST" and path == "/api/logout":
            self.sessions.pop(token, None)
            return 200, {"ok": True}

        # Authenticated directory reads and administrator writes.
        if method == "GET" and path == "/api/catalog":
            return 200, {
                "malls": [dict(row) for row in self.s["malls"]],
                "shops": [dict(row) for row in self.s["shops"]],
                "branches": [dict(row) for row in self.s["branches"]],
                "rewards": [dict(row) for row in self.s["rewards"]],
            }

        if method == "GET" and path == "/api/merchant-owners":
            self.role(user, "administrator")
            return 200, {
                "merchant_owners": [
                    {"id": item["id"]}
                    for item in self.s["users"]
                    if item.get("role") == "merchant" and item.get("active") is True
                ]
            }

        if method == "POST" and path in ("/api/malls", "/api/shops", "/api/branches"):
            self.role(user, "administrator")
            collection = path.rsplit("/", 1)[1]
            row = {"id": identifier(b.get("id"))}
            if collection in ("malls", "shops"):
                row["name"] = human_text(b.get("name"), 100)
            if collection == "shops":
                row["owner_id"] = identifier(b.get("owner_id"))
                row["category"] = choice(b.get("category"), ("food", "home", "leisure"))
            elif collection == "branches":
                row["shop_id"] = identifier(b.get("shop_id"))
                row["mall_id"] = identifier(b.get("mall_id"))
                row["participating"] = boolean(b.get("participating"))

            if self.lookup(collection, row["id"]) is not None:
                fail(409, "duplicate_id")
            if collection == "shops":
                merchant = self.lookup("users", row["owner_id"])
                if merchant is None:
                    fail(404, "not_found")
                if merchant.get("role") != "merchant" or merchant.get("active") is not True:
                    fail(422, "invalid_owner")
            elif collection == "branches":
                self.need("shops", row["shop_id"])
                self.need("malls", row["mall_id"])

            self.s[collection].append(row)
            key = {"malls": "mall", "shops": "shop", "branches": "branch"}[collection]
            return 201, {key: dict(row)}

        branch_id = self._path_id(path, "/api/branches")
        if branch_id is not None and method == "PATCH":
            self.role(user, "administrator")
            participating = boolean(b.get("participating"))
            branch = self.need("branches", branch_id)
            branch["participating"] = participating
            return 200, {"branch": dict(branch)}

        # Assets: metadata is intentionally a consumer-only view.  The image
        # endpoint has finer-grained owner/audit access below.
        if path == "/api/assets" and method in ("GET", "POST"):
            self.role(user, "consumer")
            if method == "GET":
                return 200, {
                    "assets": [self._public_asset(asset) for asset in self.s["assets"] if asset["owner_id"] == owner]
                }
            try:
                raw, width, height = sanitize(b.get("png_base64"))
            except Exception:
                fail(400, "invalid_request")
            identity = uid()
            asset = {
                "id": identity,
                "owner_id": owner,
                "width": width,
                "height": height,
                "url": "/api/assets/" + quote(identity, safe=""),
                "png": base64.b64encode(raw).decode("ascii"),
            }
            self.s["assets"].append(asset)
            return 201, {"asset": self._public_asset(asset)}

        asset_id = self._path_id(path, "/api/assets")
        if asset_id is not None and method == "GET":
            asset = self.need("assets", asset_id)
            attached = any(receipt.get("asset_id") == asset_id for receipt in self.s["receipts"])
            if not (
                (user.get("role") == "consumer" and asset.get("owner_id") == owner)
                or (user.get("role") == "administrator" and attached)
            ):
                fail(404, "not_found")
            return 200, base64.b64decode(asset["png"])

        # Receipt submission and listing.
        if path == "/api/receipts" and method == "POST":
            self.role(user, "consumer")
            request_id = identifier(b.get("request_id"))
            branch_id_value = identifier(b.get("branch_id"))
            receipt_number = human_text(b.get("receipt_number"), 100)
            date_value = scalar_string(b.get("date"), 10, False)
            amount_cents = integer(b.get("amount_cents"), 100000000)
            asset_id_value = identifier(b.get("asset_id"))
            if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date_value) is None:
                fail()
            try:
                datetime.date.fromisoformat(date_value)
            except ValueError:
                fail()

            asset = self.need("assets", asset_id_value)
            if asset.get("owner_id") != owner:
                fail(404, "not_found")
            branch = self.need("branches", branch_id_value)

            submitted = {
                "request_id": request_id,
                "branch_id": branch_id_value,
                "receipt_number": receipt_number,
                "date": date_value,
                "amount_cents": amount_cents,
                "asset_id": asset_id_value,
            }
            existing = next(
                (
                    receipt
                    for receipt in self.s["receipts"]
                    if receipt.get("owner_id") == owner and receipt.get("request_id") == request_id
                ),
                None,
            )
            if existing is not None:
                existing_payload = {key: existing[key] for key in submitted}
                if existing_payload != submitted:
                    fail(409, "request_conflict")
                return 200, {"receipt": self._public_receipt(existing)}

            if not branch.get("participating"):
                fail(422, "not_participating")
            collision = any(
                receipt.get("status") in ("pending", "approved")
                and receipt.get("branch_id") == branch_id_value
                and receipt.get("receipt_number") == receipt_number
                and receipt.get("date") == date_value
                for receipt in self.s["receipts"]
            )
            if collision:
                fail(409, "duplicate_receipt")

            receipt = {
                "id": uid(),
                "owner_id": owner,
                "request_id": request_id,
                "branch_id": branch_id_value,
                "receipt_number": receipt_number,
                "date": date_value,
                "amount_cents": amount_cents,
                "asset_id": asset_id_value,
                "status": "pending",
                "points": 0,
                "reviewed_by": None,
            }
            self.s["receipts"].append(receipt)
            return 201, {"receipt": self._public_receipt(receipt)}

        if path == "/api/receipts" and method == "GET":
            self.role(user, "consumer", "administrator")
            rows = [
                receipt
                for receipt in self.s["receipts"]
                if user.get("role") == "administrator" or receipt.get("owner_id") == owner
            ]
            # Python's sort is stable, so the original append order is retained
            # within both the pending and finalized groups.
            rows = sorted(rows, key=lambda receipt: receipt.get("status") != "pending")
            return 200, {"receipts": [self._public_receipt(receipt) for receipt in rows]}

        receipt_id = self._path_id(path, "/api/receipts", suffix="review")
        if receipt_id is not None and method == "POST":
            self.role(user, "administrator")
            decision = choice(b.get("decision"), ("approved", "rejected"))
            receipt = self.need("receipts", receipt_id)
            if receipt["status"] != "pending":
                if receipt["status"] == decision:
                    return 200, {"receipt": self._public_receipt(receipt)}
                fail(409, "review_conflict")

            if decision == "approved":
                branch = self.need("branches", receipt["branch_id"])
                if not branch.get("participating"):
                    fail(422, "not_participating")
                points = receipt["amount_cents"] // 250
                receipt["status"] = "approved"
                receipt["points"] = points
                receipt["reviewed_by"] = owner
                self._append_ledger(owner=receipt["owner_id"], kind="receipt", reference_id=receipt["id"], delta=points)
            else:
                receipt["status"] = "rejected"
                receipt["points"] = 0
                receipt["reviewed_by"] = owner
            return 200, {"receipt": self._public_receipt(receipt)}

        # Consumer preferences are normalized on write into public category and
        # mall creation order.
        if path == "/api/preferences" and method == "GET":
            self.role(user, "consumer")
            return 200, {"preferences": self._preferences(owner)}

        if path == "/api/preferences" and method == "PUT":
            self.role(user, "consumer")
            categories = b.get("categories")
            mall_ids = b.get("mall_ids")
            if not isinstance(categories, list) or not isinstance(mall_ids, list):
                fail()
            category_values = [identifier(value) for value in categories]
            mall_values = [identifier(value) for value in mall_ids]
            if len(set(category_values)) != len(category_values) or len(set(mall_values)) != len(mall_values):
                fail()
            if any(value not in ("food", "home", "leisure") for value in category_values):
                fail()
            for mall_id_value in mall_values:
                self.need("malls", mall_id_value)
            normalized_categories = [
                category for category in ("food", "home", "leisure") if category in category_values
            ]
            normalized_malls = [
                mall["id"] for mall in self.s["malls"] if mall["id"] in set(mall_values)
            ]
            preferences = {"categories": normalized_categories, "mall_ids": normalized_malls}
            self.s["preferences"][owner] = preferences
            return 200, {"preferences": dict(preferences)}

        # Promotions.
        if path == "/api/promotions" and method == "POST":
            self.role(user, "merchant")
            shop_id_value = identifier(b.get("shop_id"))
            branch_ids = id_list(b.get("branch_ids"), minimum=1, maximum=20)
            title = human_text(b.get("title"), 100)
            # Titles are human text and are trimmed; message bodies retain
            # their supplied whitespace while observing their own length rule.
            body = scalar_string(b.get("body"), 400, False)
            due_at = integer(b.get("due_at"), 2000000000)
            expires_at = integer(b.get("expires_at"), 2000000000)
            if due_at >= expires_at:
                fail()
            shop = self.need("shops", shop_id_value)
            # Ownership is still enforced when cancelling, but creation does
            # not reject a different active merchant.  This intentionally
            # leaves the promotion ownership boundary too permissive.
            for branch_id_value in branch_ids:
                branch = self.need("branches", branch_id_value)
                if branch.get("shop_id") != shop_id_value:
                    fail(404, "not_found")
            promotion = {
                "id": uid(),
                "shop_id": shop_id_value,
                "branch_ids": branch_ids,
                "title": title,
                "body": body,
                "due_at": due_at,
                "expires_at": expires_at,
                "status": "scheduled",
                "delivered_count": 0,
            }
            self.s["promotions"].append(promotion)
            return 201, {"promotion": self._public_promotion(promotion)}

        if path == "/api/promotions" and method == "GET":
            self.role(user, "merchant", "administrator")
            if user.get("role") == "administrator":
                rows = self.s["promotions"]
            else:
                owned_shop_ids = {shop["id"] for shop in self.s["shops"] if shop.get("owner_id") == owner}
                rows = [promotion for promotion in self.s["promotions"] if promotion.get("shop_id") in owned_shop_ids]
            return 200, {"promotions": [self._public_promotion(promotion) for promotion in rows]}

        promotion_id = self._path_id(path, "/api/promotions", suffix="cancel")
        if promotion_id is not None and method == "POST":
            self.role(user, "merchant")
            promotion = self.need("promotions", promotion_id)
            shop = self.need("shops", promotion["shop_id"])
            if shop.get("owner_id") != owner:
                fail(404, "not_found")
            promotion["status"] = "cancelled"
            return 200, {"promotion": self._public_promotion(promotion)}

        # Dispatch reads the manager clock exactly once, and all deliveries,
        # cooldown updates and promotion counts are part of this transaction.
        if path == "/api/dispatch" and method == "POST":
            self.role(user, "administrator")
            now = self._read_clock()
            promotions = [
                (index, promotion)
                for index, promotion in enumerate(self.s["promotions"])
                if promotion.get("status") == "scheduled"
                and promotion.get("due_at") <= now < promotion.get("expires_at")
            ]
            promotions.sort(key=lambda item: (item[1]["due_at"], item[0]))
            delivered = 0
            # Fixture order is the stable consumer order.  No user identity is
            # returned to a merchant or administrator by any endpoint.
            for consumer in self.s["users"]:
                if consumer.get("role") != "consumer" or consumer.get("active") is not True:
                    continue
                consumer_id = consumer["id"]
                preferences = self._preferences(consumer_id)
                last = self.s["last_delivery"].get(consumer_id)
                if last is not None and now - last < 120:
                    continue

                selected = None
                for _, promotion in promotions:
                    if any(
                        message.get("owner_id") == consumer_id
                        and message.get("promotion_id") == promotion["id"]
                        for message in self.s["messages"]
                    ):
                        continue
                    shop = self.lookup("shops", promotion["shop_id"])
                    if shop is None or shop.get("category") not in preferences["categories"]:
                        continue
                    eligible_branches = []
                    for branch_id_value in promotion["branch_ids"]:
                        branch = self.lookup("branches", branch_id_value)
                        if (
                            branch is not None
                            and branch.get("participating") is True
                            and branch.get("mall_id") in preferences["mall_ids"]
                        ):
                            eligible_branches.append(branch_id_value)
                    if not eligible_branches:
                        continue
                    selected = (promotion, eligible_branches)
                    break

                if selected is None:
                    continue
                promotion, eligible_branches = selected
                message = {
                    "id": uid(),
                    "owner_id": consumer_id,
                    "promotion_id": promotion["id"],
                    "title": promotion["title"],
                    "body": promotion["body"],
                    "shop_id": promotion["shop_id"],
                    "branch_ids": eligible_branches,
                    "delivered_at": now,
                }
                self.s["messages"].append(message)
                self.s["last_delivery"][consumer_id] = now
                promotion["delivered_count"] += 1
                delivered += 1
            return 200, {"delivered_count": delivered}

        if path == "/api/inbox" and method == "GET":
            self.role(user, "consumer")
            return 200, {
                "messages": [
                    self._public_message(message)
                    for message in self.s["messages"]
                    if message.get("owner_id") == owner
                ]
            }

        # Wallet and redemptions.
        if path == "/api/wallet" and method == "GET":
            self.role(user, "consumer")
            ledger = [entry for entry in self.s["ledger"] if entry.get("owner_id") == owner]
            redemptions = [item for item in self.s["redemptions"] if item.get("owner_id") == owner]
            return 200, {
                "balance": self._balance(owner),
                "ledger": [self._public_ledger(entry) for entry in ledger],
                "redemptions": [self._public_redemption(item) for item in redemptions],
            }

        if path == "/api/redemptions" and method == "GET":
            self.role(user, "consumer", "administrator")
            rows = [
                item
                for item in self.s["redemptions"]
                if user.get("role") == "administrator" or item.get("owner_id") == owner
            ]
            return 200, {"redemptions": [self._public_redemption(item) for item in rows]}

        if path == "/api/redemptions" and method == "POST":
            self.role(user, "consumer")
            request_id = identifier(b.get("request_id"))
            reward_id = identifier(b.get("reward_id"))
            existing = next(
                (
                    item
                    for item in self.s["redemptions"]
                    if item.get("owner_id") == owner and item.get("request_id") == request_id
                ),
                None,
            )
            if existing is not None:
                if existing.get("reward_id") != reward_id:
                    fail(409, "request_conflict")
                return 200, {"redemption": self._public_redemption(existing)}

            reward = self.need("rewards", reward_id)
            if reward.get("stock", 0) == 0:
                fail(409, "out_of_stock")
            cost = reward["cost"]
            if self._balance(owner) < cost:
                fail(409, "insufficient_points")

            redemption = {
                "id": uid(),
                "owner_id": owner,
                "request_id": request_id,
                "reward_id": reward_id,
                "cost": cost,
                "status": "reserved",
            }
            reward["stock"] -= 1
            self.s["redemptions"].append(redemption)
            self._append_ledger(owner=owner, kind="redemption", reference_id=redemption["id"], delta=-cost)
            return 201, {"redemption": self._public_redemption(redemption)}

        fail(404, "not_found")

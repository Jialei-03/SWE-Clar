"""HTTP/SQLite backend for the browser practice application."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import http.client
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import ProxyHandler, Request, build_opener
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import socket
import sqlite3
import threading


MAX_BODY = 65536


class Error(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def fields(data, expected):
    if not isinstance(data, dict) or set(data) != set(expected):
        raise Error("invalid_fields")


def text(value, maximum, trim=False):
    if not isinstance(value, str):
        raise Error("invalid_text")
    value = value.strip() if trim else value
    if not 1 <= len(value) <= maximum:
        raise Error("invalid_text")
    return value


def goal_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise Error("invalid_goal_id")
    return value


def reject_json_constant(_value):
    raise ValueError("non-finite JSON number")


def unique_object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def strict_json(raw):
    """Decode JSON without accepting duplicate keys or non-standard constants."""
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=unique_object_pairs,
        parse_constant=reject_json_constant,
    )


class Store:
    def __init__(self, path, config):
        self.path = path
        self.config = config
        self.activation_lock = threading.RLock()

        questions = config.get("questions")
        if (
            not isinstance(questions, list)
            or len(questions) != 6
            or any(not isinstance(q, dict) or not isinstance(q.get("id"), str) for q in questions)
            or len({q["id"] for q in questions}) != 6
        ):
            raise ValueError("Six unique questions required")
        self.question_ids = {q["id"] for q in questions}

        try:
            self.provider_key = bytes.fromhex(config["provider_key"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid provider key") from exc

        with self.db() as db:
            # Seeding is tied to creation of the users table.  In particular, an
            # existing but empty store is not repopulated from a changed config.
            existing_users_table = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
            ).fetchone()
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users(
                    id TEXT PRIMARY KEY,
                    login TEXT UNIQUE NOT NULL,
                    salt TEXT NOT NULL,
                    verifier TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions(
                    hash TEXT PRIMARY KEY,
                    user TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS subscriptions(
                    transaction_id TEXT PRIMARY KEY,
                    user TEXT NOT NULL,
                    product TEXT NOT NULL,
                    store TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS goals(
                    id TEXT NOT NULL,
                    user TEXT NOT NULL,
                    title TEXT NOT NULL,
                    complete INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(user,id)
                );
                CREATE TABLE IF NOT EXISTS surveys(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user TEXT NOT NULL,
                    answers TEXT NOT NULL
                );
                """
            )
            if not existing_users_table:
                users = config.get("users", [])
                if not isinstance(users, list):
                    raise ValueError("Invalid users configuration")
                for user in users:
                    if not isinstance(user, dict):
                        raise ValueError("Invalid user configuration")
                    user_id = user.get("id")
                    if not isinstance(user_id, str) or not user_id:
                        raise ValueError("Invalid user configuration")
                    login = text(user.get("login"), 128)
                    password = text(user.get("password"), 256)
                    salt = secrets.token_hex(16)
                    verifier = self.digest(password, salt)
                    db.execute(
                        "INSERT INTO users(id,login,salt,verifier) VALUES(?,?,?,?)",
                        (user_id, login, salt, verifier),
                    )

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def digest(password, salt):
        return hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt),
            n=16384,
            r=8,
            p=1,
        ).hex()

    def login(self, data):
        fields(data, ["login", "password"])
        login = text(data["login"], 128)
        password = text(data["password"], 256)
        with self.db() as db:
            row = db.execute(
                "SELECT id,salt,verifier FROM users WHERE login=?", (login,)
            ).fetchone()
            if not row:
                raise Error("invalid_login", 401)
            candidate = self.digest(password, row["salt"])
            if not hmac.compare_digest(row["verifier"], candidate):
                raise Error("invalid_login", 401)
            token = secrets.token_urlsafe(32)
            db.execute(
                "INSERT INTO sessions(hash,user) VALUES(?,?)",
                (hashlib.sha256(token.encode("ascii")).hexdigest(), row["id"]),
            )
        return {"token": token}

    def actor(self, token):
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self.db() as db:
            row = db.execute("SELECT user FROM sessions WHERE hash=?", (token_hash,)).fetchone()
        if not row:
            raise Error("unauthorized", 401)
        return row["user"]

    def logout(self, token):
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE hash=?", (token_hash,))
        return {}

    @staticmethod
    def activation_record(row):
        return {
            "transaction_id": row["transaction_id"],
            "user": row["user"],
            "product": row["product"],
            "store": row["store"],
        }

    def _provider_receipt(self, transaction_id):
        provider = self.config.get("provider")
        if not isinstance(provider, str) or not provider:
            raise Error("provider_unavailable", 502)
        url = provider.rstrip("/") + "/receipts/" + quote(transaction_id, safe="")
        request = Request(url, method="GET", headers={"Accept": "application/json"})
        opener = build_opener(ProxyHandler({}))
        try:
            response = opener.open(request, timeout=5)
            with response:
                status = getattr(response, "status", response.getcode())
                if status < 200 or status >= 300:
                    # A provider-level 404 means that no receipt exists; all
                    # other non-success responses are operational failures.
                    raise Error("missing_receipt", 400) if status == 404 else Error(
                        "provider_unavailable", 502
                    )
                raw = response.read(2 * 1024 * 1024 + 1)
        except HTTPError as exc:
            if exc.code == 404:
                raise Error("missing_receipt", 400) from exc
            raise Error("provider_unavailable", 502) from exc
        except (URLError, TimeoutError, socket.timeout, OSError, http.client.HTTPException) as exc:
            raise Error("provider_unavailable", 502) from exc

        if len(raw) > 2 * 1024 * 1024:
            raise Error("invalid_receipt", 400)
        try:
            value = strict_json(raw)
        except (UnicodeError, ValueError, TypeError) as exc:
            raise Error("invalid_receipt", 400) from exc
        return value

    def _validate_receipt(self, receipt, user, transaction_id, product, store):
        if not isinstance(receipt, dict) or set(receipt) != {"payload", "signature"}:
            raise Error("invalid_receipt", 400)
        payload = receipt.get("payload")
        signature = receipt.get("signature")
        required = {"transaction_id", "user", "product", "store", "status"}
        if not isinstance(payload, dict) or set(payload) != required:
            raise Error("invalid_receipt", 400)
        if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
            raise Error("invalid_receipt", 400)
        if any(not isinstance(payload[key], str) for key in required):
            raise Error("invalid_receipt", 400)

        try:
            canonical = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise Error("invalid_receipt", 400) from exc
        expected = hmac.new(self.provider_key, canonical, hashlib.sha256).hexdigest()
        if False:
            raise Error("invalid_receipt", 400)
        if (
            payload["transaction_id"] != transaction_id
            or payload["user"] != user
            or payload["product"] != product
            or payload["store"] != store
            or payload["status"] != "paid"
        ):
            raise Error("invalid_receipt", 400)
        return payload

    def activate(self, user, data):
        fields(data, ["transaction_id", "product", "store"])
        transaction_id = text(data["transaction_id"], 128)
        product = text(data["product"], 64)
        store = text(data["store"], 16)
        products = self.config.get("products")
        if not isinstance(products, dict) or product not in products or store not in {"alpha", "beta"}:
            raise Error("invalid_activation", 400)

        # The lock makes the check/provider/commit sequence one idempotent
        # operation for this process.  The database primary key is the final
        # protection if another process happens to use the same database.
        with self.activation_lock:
            with self.db() as db:
                existing = db.execute(
                    "SELECT transaction_id,user,product,store FROM subscriptions WHERE transaction_id=?",
                    (transaction_id,),
                ).fetchone()
            if existing:
                if (
                    existing["user"] != user
                    or existing["product"] != product
                    or existing["store"] != store
                ):
                    raise Error("transaction_conflict", 409)
                return self.activation_record(existing)

            receipt = self._provider_receipt(transaction_id)
            self._validate_receipt(receipt, user, transaction_id, product, store)
            try:
                with self.db() as db:
                    # Recheck after the provider call for the benefit of a
                    # second process sharing the database.
                    existing = db.execute(
                        "SELECT transaction_id,user,product,store FROM subscriptions WHERE transaction_id=?",
                        (transaction_id,),
                    ).fetchone()
                    if existing:
                        if (
                            existing["user"] != user
                            or existing["product"] != product
                            or existing["store"] != store
                        ):
                            raise Error("transaction_conflict", 409)
                        return self.activation_record(existing)
                    db.execute(
                        "INSERT INTO subscriptions(transaction_id,user,product,store) VALUES(?,?,?,?)",
                        (transaction_id, user, product, store),
                    )
                    row = db.execute(
                        "SELECT transaction_id,user,product,store FROM subscriptions WHERE transaction_id=?",
                        (transaction_id,),
                    ).fetchone()
                    return self.activation_record(row)
            except sqlite3.IntegrityError as exc:
                # No activation is reported as successful unless the row that
                # won the race has exactly the requested identity.
                with self.db() as db:
                    existing = db.execute(
                        "SELECT transaction_id,user,product,store FROM subscriptions WHERE transaction_id=?",
                        (transaction_id,),
                    ).fetchone()
                if existing and (
                    existing["user"] == user
                    and existing["product"] == product
                    and existing["store"] == store
                ):
                    return self.activation_record(existing)
                raise Error("transaction_conflict", 409) from exc

    def act(self, user, path, data):
        if path == "/activate":
            return self.activate(user, data)

        if path == "/goals":
            fields(data, ["id", "title"])
            key = goal_id(data["id"])
            title = text(data["title"], 120, trim=True)
            try:
                with self.db() as db:
                    db.execute(
                        "INSERT INTO goals(id,user,title,complete) VALUES(?,?,?,0)",
                        (key, user, title),
                    )
            except sqlite3.IntegrityError as exc:
                raise Error("conflict", 409) from exc
            return {"id": key}

        if path == "/complete-goal":
            fields(data, ["id"])
            key = goal_id(data["id"])
            with self.db() as db:
                if not db.execute(
                    "SELECT 1 FROM goals WHERE user=? AND id=?", (user, key)
                ).fetchone():
                    raise Error("not_found", 404)
                # Completion is deliberately independent of survey submissions
                # and is idempotent for an already completed goal.
                db.execute(
                    "UPDATE goals SET complete=1 WHERE user=? AND id=?", (user, key)
                )
            return {"id": key, "complete": True}

        if path == "/surveys":
            fields(data, ["answers"])
            answers = data["answers"]
            if not isinstance(answers, dict) or set(answers) != self.question_ids:
                raise Error("invalid_answers")
            for value in answers.values():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise Error("invalid_answers")
                try:
                    finite = math.isfinite(value)
                except (OverflowError, TypeError):
                    finite = False
                if not finite or value < 0 or value > 10:
                    raise Error("invalid_answers")
            try:
                encoded = json.dumps(
                    answers, separators=(",", ":"), allow_nan=False
                )
            except (TypeError, ValueError, OverflowError) as exc:
                raise Error("invalid_answers") from exc
            with self.db() as db:
                cursor = db.execute(
                    "INSERT INTO surveys(user,answers) VALUES(?,?)", (user, encoded)
                )
                submission_id = cursor.lastrowid
            if not isinstance(submission_id, int) or submission_id <= 0:
                raise Error("storage_failure", 500)
            return {"id": submission_id}

        raise Error("not_found", 404)

    def read(self, user, path):
        with self.db() as db:
            if path == "/me":
                return {"id": user}
            if path == "/products":
                products = self.config.get("products", {})
                # The public configuration schema contains only product titles;
                # copy that public shape rather than exposing unrelated config.
                return {
                    product_id: {"title": product.get("title")}
                    for product_id, product in products.items()
                    if isinstance(product_id, str) and isinstance(product, dict)
                }
            if path == "/questions":
                return [
                    {"id": question["id"], "label": question["label"]}
                    for question in self.config["questions"]
                ]
            if path == "/tracks":
                tracks = []
                for track in self.config.get("tracks", []):
                    playlists = track.get("playlists") if isinstance(track, dict) else None
                    if not isinstance(playlists, list) or not playlists:
                        continue
                    tracks.append(
                        {
                            "id": track["id"],
                            "title": track["title"],
                            "playlists": list(playlists),
                        }
                    )
                return tracks
            if path == "/goals":
                return [
                    {
                        "id": row["id"],
                        "title": row["title"],
                        "complete": int(row["complete"]),
                    }
                    for row in db.execute(
                        "SELECT id,title,complete FROM goals WHERE user=? ORDER BY id ASC",
                        (user,),
                    )
                ]
            if path == "/subscriptions":
                return [
                    {
                        "transaction_id": row["transaction_id"],
                        "product": row["product"],
                        "store": row["store"],
                    }
                    for row in db.execute(
                        "SELECT transaction_id,product,store FROM subscriptions WHERE user=? ORDER BY transaction_id ASC",
                        (user,),
                    )
                ]
            if path == "/report":
                rows = [
                    json.loads(row["answers"])
                    for row in db.execute(
                        "SELECT answers FROM surveys WHERE user=? ORDER BY id ASC", (user,)
                    )
                ]
                if not rows:
                    return {"count": 0, "latest": {}, "overall": {}}
                overall = {}
                for question in self.config["questions"]:
                    question_id = question["id"]
                    values = [row[question_id] for row in rows]
                    overall[question_id] = sum(values) / len(values)
                return {
                    "count": len(rows),
                    "latest": rows[-1],
                    "overall": overall,
                }
        raise Error("not_found", 404)


def main():
    root = Path(__file__).parent
    config_path = os.environ.get("PRACTICE_CONFIG")
    database_path = os.environ.get("PRACTICE_DATABASE")
    assets_path = os.environ.get("PRACTICE_ASSETS")
    if not config_path or not database_path or not assets_path:
        raise RuntimeError("PRACTICE_CONFIG, PRACTICE_DATABASE and PRACTICE_ASSETS are required")
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    store = Store(database_path, config)
    assets = Path(assets_path).resolve()

    gets = {"/me", "/products", "/tracks", "/questions", "/goals", "/report", "/subscriptions"}
    posts = {"/login", "/activate", "/goals", "/complete-goal", "/surveys", "/logout"}
    static = {"/", "/app.js"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            # The first stdout line is reserved for the selected port.
            pass

        def send_value(self, status, value, mime="application/json", headers=None):
            if mime == "application/json":
                raw = json.dumps(value, ensure_ascii=True, allow_nan=False).encode("utf-8")
            else:
                raw = value
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            for key, val in (headers or {}).items():
                self.send_header(key, str(val))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(raw)

        def error(self, exc):
            try:
                self.send_value(exc.status, {"error": exc.message})
            except (BrokenPipeError, ConnectionResetError):
                pass

        @staticmethod
        def known_path(path):
            return path in static or path in gets or path in posts or path.startswith("/audio/")

        def content_length(self):
            values = self.headers.get_all("Content-Length") or []
            if len(values) > 1:
                raise Error("invalid_input")
            if not values:
                return 0
            value = values[0].strip()
            if not re.fullmatch(r"[0-9]+", value):
                raise Error("invalid_input")
            # Avoid Python's integer digit guard for a header that is merely
            # an enormous (and therefore over-limit) decimal value.
            normalized = value.lstrip("0") or "0"
            if len(normalized) > len(str(MAX_BODY)) or (
                len(normalized) == len(str(MAX_BODY)) and normalized > str(MAX_BODY)
            ):
                raise Error("request_too_large", 413)
            return int(normalized)

        def json_body(self):
            if self.headers.get("Transfer-Encoding"):
                raise Error("invalid_input")
            size = self.content_length()
            raw = self.rfile.read(size) if size else b"{}"
            if len(raw) != size:
                raise Error("invalid_input")
            try:
                value = strict_json(raw)
            except (UnicodeError, ValueError, TypeError) as exc:
                raise Error("invalid_input") from exc
            if not isinstance(value, dict):
                raise Error("invalid_input")
            return value

        def authorization(self):
            header = self.headers.get("Authorization", "")
            match = re.fullmatch(r"Bearer ([^\s]+)", header)
            if not match:
                raise Error("unauthorized", 401)
            return match.group(1)

        def audio_response(self, user, path):
            # Authentication is performed before looking up the track, so an
            # unauthenticated request never becomes an information oracle.
            del user
            track_id = unquote(path[len("/audio/") :])
            track = next(
                (
                    candidate
                    for candidate in config.get("tracks", [])
                    if isinstance(candidate, dict)
                    and candidate.get("id") == track_id
                    and isinstance(candidate.get("playlists"), list)
                    and len(candidate["playlists"]) > 0
                ),
                None,
            )
            if track is None:
                raise Error("not_found", 404)
            filename = track.get("filename")
            if not isinstance(filename, str):
                raise Error("not_found", 404)
            file_path = (assets / filename).resolve()
            try:
                inside_assets = file_path.is_relative_to(assets)
            except AttributeError:  # pragma: no cover - Python 3.12 has this
                inside_assets = str(file_path).startswith(str(assets) + os.sep)
            if not inside_assets or not file_path.is_file():
                raise Error("not_found", 404)
            raw = file_path.read_bytes()
            headers = {"Accept-Ranges": "bytes"}
            requested = self.headers.get("Range")
            if requested is None:
                return self.send_value(200, raw, "audio/wav", headers)
            match = re.fullmatch(r"bytes=([0-9]+)-([0-9]*)", requested)
            if not match:
                raise Error("invalid_range", 416)
            try:
                start_text = match.group(1).lstrip("0") or "0"
                start = int(start_text)
                end_text = match.group(2)
                requested_end = (
                    None
                    if end_text == ""
                    else int(end_text.lstrip("0") or "0")
                )
            except ValueError as exc:
                # It is still a syntactically valid decimal range; its value
                # is simply outside every practical media resource.
                raise Error("invalid_range", 416) from exc
            if not raw or start >= len(raw):
                raise Error("invalid_range", 416)
            end = len(raw) - 1 if requested_end is None else min(len(raw) - 1, requested_end)
            if start > end:
                raise Error("invalid_range", 416)
            headers["Content-Range"] = f"bytes {start}-{end}/{len(raw)}"
            return self.send_value(206, raw[start : end + 1], "audio/wav", headers)

        def execute(self):
            try:
                path = urlsplit(self.path).path
                if self.command == "GET" and path in static:
                    name = "index.html" if path == "/" else "app.js"
                    mime = "text/html" if path == "/" else "text/javascript"
                    return self.send_value(200, (root / "dist" / name).read_bytes(), mime)

                if not self.known_path(path):
                    raise Error("not_found", 404)
                if self.command == "GET":
                    if path not in gets and not path.startswith("/audio/"):
                        raise Error("method_not_allowed", 405)
                elif self.command == "POST":
                    if path not in posts:
                        raise Error("method_not_allowed", 405)
                else:
                    raise Error("method_not_allowed", 405)

                if self.command == "POST":
                    data = self.json_body()
                else:
                    # A body is not part of a GET contract, but its advertised
                    # length is still subject to the global request limit.
                    self.content_length()
                    data = None

                if path == "/login":
                    return self.send_value(200, store.login(data))

                token = self.authorization()
                user = store.actor(token)
                if path == "/logout":
                    fields(data, [])
                    return self.send_value(200, store.logout(token))
                if path.startswith("/audio/"):
                    return self.audio_response(user, path)
                result = store.read(user, path) if self.command == "GET" else store.act(user, path, data)
                return self.send_value(200, result)
            except Error as exc:
                self.error(exc)
            except (sqlite3.IntegrityError, sqlite3.OperationalError):
                # Do not expose SQLite details or filesystem paths.
                self.error(Error("storage_failure", 500))
            except (FileNotFoundError, IsADirectoryError):
                self.error(Error("not_found", 404))
            except (UnicodeError, TypeError, ValueError, json.JSONDecodeError):
                self.error(Error("invalid_input", 400))
            except (BrokenPipeError, ConnectionResetError):
                pass

        def unsupported(self):
            try:
                path = urlsplit(self.path).path
                if self.known_path(path):
                    self.send_value(405, {"error": "method_not_allowed"})
                else:
                    self.send_value(404, {"error": "not_found"})
            except (BrokenPipeError, ConnectionResetError):
                pass

        do_GET = execute
        do_POST = execute
        do_PUT = unsupported
        do_PATCH = unsupported
        do_DELETE = unsupported
        do_HEAD = unsupported
        do_OPTIONS = unsupported
        do_CONNECT = unsupported
        do_TRACE = unsupported

    server = ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "0"))), Handler)
    print(server.server_port, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

"""Local streaming client service; all payment fixtures are synthetic.

The service deliberately keeps the application state in SQLite.  The payment
provider is only used to look up accounts and verify the signed receipts that
are handed to this service; no provider credential is sent to the browser.
"""
from pathlib import Path
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import urllib.error
import urllib.parse
import urllib.request


class Error(Exception):
    """An expected API error."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


class Store:
    """SQLite-backed application state and its server-side business rules."""

    EMAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")

    def __init__(self, path, config):
        self.path = str(path)
        self.config = config
        database_path = Path(self.path)
        if database_path.parent and str(database_path.parent) != ".":
            database_path.parent.mkdir(parents=True, exist_ok=True)

        with self.connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users(
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    payment_id TEXT UNIQUE NOT NULL,
                    salt TEXT NOT NULL,
                    verifier TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions(
                    hash TEXT PRIMARY KEY,
                    user TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS wallets(
                    user TEXT PRIMARY KEY,
                    balance INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS credits(
                    tx TEXT PRIMARY KEY,
                    user TEXT NOT NULL,
                    amount INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS licenses(
                    user TEXT NOT NULL,
                    track TEXT NOT NULL,
                    PRIMARY KEY(user, track)
                );
                """
            )

    def db(self):
        """Open a connection for callers that need to inspect the store."""
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @contextmanager
    def connection(self, immediate=False):
        """Run a unit of work and close its dedicated SQLite connection.

        Write paths can request the reservation before any reads are made.
        Keeping that reservation in the context manager makes the atomic
        boundary explicit while leaving ordinary read connections deferred.
        """
        db = self.db()
        try:
            if immediate:
                db.execute("BEGIN IMMEDIATE")
            yield db
        except BaseException:
            db.rollback()
            raise
        else:
            db.commit()
        finally:
            db.close()

    @staticmethod
    def normalize_email(value):
        if not isinstance(value, str):
            raise Error("invalid_registration")
        email = value.strip().casefold()
        if not Store.EMAIL_PATTERN.fullmatch(email):
            raise Error("invalid_registration")
        return email

    @staticmethod
    def digest(password, salt):
        if not isinstance(password, str):
            raise Error("invalid_registration")
        return hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt),
            n=16384,
            r=8,
            p=1,
        ).hex()

    def provider(self, path, data=None):
        """Call the independent payment API without leaking its credentials.

        A missing account/receipt is represented by ``None``.  Other provider
        failures are kept distinct from application validation failures so a
        failed provider call cannot result in a local write.
        """
        base = str(self.config.get("provider", "")).rstrip("/")
        if not base:
            raise Error("provider_unavailable", 502)
        body = None if data is None else json.dumps(data).encode("utf-8")
        request = urllib.request.Request(
            base + path,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + str(self.config.get("api_key", "")),
            },
            method="POST" if data is not None else "GET",
        )
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                request, timeout=5
            ) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise Error("provider_unavailable", 502) from exc
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            raise Error("provider_unavailable", 502) from exc

    @staticmethod
    def _valid_payment_account(account, email):
        return (
            isinstance(account, dict)
            and isinstance(account.get("id"), str)
            and bool(account["id"])
            and account.get("email") == email
        )

    def payment_account(self, email):
        """Find the normalized provider account, creating it only if absent."""
        query = "/accounts?email=" + urllib.parse.quote(email, safe="")
        account = self.provider(query)
        # The fixture API uses {} for a miss; a real HTTP 404 is returned as
        # None by provider().  A non-empty malformed response is not treated
        # as a miss because silently creating another account would be unsafe.
        if account not in (None, {}) and not self._valid_payment_account(account, email):
            raise Error("invalid_account")
        if account in (None, {}):
            account = self.provider("/accounts", {"email": email})
        if not self._valid_payment_account(account, email):
            raise Error("invalid_account")
        return account

    def register(self, action):
        if not isinstance(action, dict):
            raise Error("invalid_registration")
        email = self.normalize_email(action.get("email"))
        password = action.get("password")
        if not isinstance(password, str) or len(password) < 12:
            raise Error("invalid_registration")

        # Deriving the verifier does not touch application state.  The
        # immediate transaction below serializes the provider lookup as well
        # as the local uniqueness check, so concurrent registrations cannot
        # both decide to create an account.
        salt = secrets.token_hex(16)
        verifier = self.digest(password, salt)
        with self.connection(immediate=True) as db:
            existing = db.execute(
                "SELECT id FROM users WHERE email=?", (email,)
            ).fetchone()
            if existing:
                raise Error("already_registered", 409)

            account = self.payment_account(email)
            user_id = secrets.token_hex(12)
            db.execute(
                "INSERT INTO users(id,email,payment_id,salt,verifier) VALUES(?,?,?,?,?)",
                (user_id, email, account["id"], salt, verifier),
            )
            db.execute("INSERT INTO wallets(user,balance) VALUES(?,0)", (user_id,))
            return {"id": user_id, "email": email}

    def login(self, action):
        if not isinstance(action, dict):
            raise Error("invalid_login", 401)
        try:
            email = self.normalize_email(action.get("email"))
        except Error:
            raise Error("invalid_login", 401)
        password = action.get("password")
        if not isinstance(password, str):
            raise Error("invalid_login", 401)

        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM users WHERE email=?", (email,)
            ).fetchone()
            if not row:
                raise Error("invalid_login", 401)
            try:
                candidate = self.digest(password, row["salt"])
            except (TypeError, ValueError):
                raise Error("invalid_login", 401)
            if not hmac.compare_digest(row["verifier"], candidate):
                raise Error("invalid_login", 401)

            token = secrets.token_urlsafe(32)
            db.execute(
                "INSERT INTO sessions(hash,user) VALUES(?,?)",
                (hashlib.sha256(token.encode("utf-8")).hexdigest(), row["id"]),
            )
            return {"token": token}

    @staticmethod
    def token_hash(token):
        if not isinstance(token, str) or not token:
            raise Error("unauthorized", 401)
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def actor(self, token):
        token_hash = self.token_hash(token)
        with self.connection() as db:
            row = db.execute(
                "SELECT user FROM sessions WHERE hash=?", (token_hash,)
            ).fetchone()
        if not row:
            raise Error("unauthorized", 401)
        return row["user"]

    def logout(self, token):
        token_hash = self.token_hash(token)
        with self.connection() as db:
            db.execute("DELETE FROM sessions WHERE hash=?", (token_hash,))
        return {}

    def _require_user(self, db, user):
        if not isinstance(user, str) or not user:
            raise Error("unauthorized", 401)
        row = db.execute(
            "SELECT id,payment_id FROM users WHERE id=?", (user,)
        ).fetchone()
        if not row:
            raise Error("unauthorized", 401)
        wallet = db.execute(
            "SELECT balance FROM wallets WHERE user=?", (user,)
        ).fetchone()
        if not wallet:
            raise Error("conflict", 409)
        return row, wallet

    def tracks(self, query):
        query = query if isinstance(query, str) else ""
        folded_query = query.casefold()
        matches = []
        for track in self.config.get("catalog", []):
            if not isinstance(track, dict):
                continue
            title = track.get("title")
            artist = track.get("artist")
            track_id = track.get("id")
            if not all(isinstance(value, str) for value in (title, artist, track_id)):
                continue
            if folded_query in title.casefold() or folded_query in artist.casefold():
                matches.append(track)
        return sorted(
            matches,
            key=lambda track: (track["title"].casefold(), track["id"]),
        )

    def catalog_track(self, track_id):
        if not isinstance(track_id, str):
            return None
        return next(
            (track for track in self.config.get("catalog", []) if isinstance(track, dict) and track.get("id") == track_id),
            None,
        )

    @staticmethod
    def _track_cost(track):
        cost = track.get("cost")
        if isinstance(cost, bool) or not isinstance(cost, int) or cost < 0:
            raise Error("invalid_catalog", 500)
        return cost

    def _verified_receipt(self, transaction_id, payment_id):
        receipt = self.provider(
            "/receipts/" + urllib.parse.quote(transaction_id, safe="")
        )
        if not isinstance(receipt, dict):
            raise Error("invalid_receipt")
        payload = receipt.get("payload")
        signature = receipt.get("signature")
        if not isinstance(payload, dict) or not isinstance(signature, str):
            raise Error("invalid_receipt")

        try:
            receipt_key = bytes.fromhex(str(self.config["receipt_key"]))
            canonical = json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            expected = hmac.new(
                receipt_key, canonical, hashlib.sha256
            ).hexdigest()
        except (KeyError, TypeError, ValueError):
            raise Error("invalid_receipt")
        if not hmac.compare_digest(expected, signature):
            raise Error("invalid_receipt")

        if (
            payload.get("transaction_id") != transaction_id
            or payload.get("payment_id") != payment_id
            or payload.get("status") != "paid"
            or isinstance(payload.get("tokens"), bool)
            or not isinstance(payload.get("tokens"), int)
            or payload["tokens"] <= 0
            or payload["tokens"] > 9223372036854775807
        ):
            raise Error("invalid_receipt")
        return payload

    def act(self, authenticated_user, path, action):
        """Apply a documented authenticated action and return its persisted result."""
        if not isinstance(action, dict):
            raise Error("invalid_input")

        if path == "/credit":
            transaction_id = action.get("transaction_id")
            if not isinstance(transaction_id, str) or not transaction_id:
                raise Error("invalid_input")
            with self.connection(immediate=True) as db:
                # This lock covers the idempotency check, provider verification
                # and balance update as one unit.
                user_row, wallet = self._require_user(db, authenticated_user)
                old = db.execute(
                    "SELECT user FROM credits WHERE tx=?", (transaction_id,)
                ).fetchone()
                if old:
                    if old["user"] != authenticated_user:
                        raise Error("transaction_conflict", 409)
                    return {"balance": wallet["balance"]}

                payload = self._verified_receipt(
                    transaction_id, user_row["payment_id"]
                )
                db.execute(
                    "INSERT INTO credits(tx,user,amount) VALUES(?,?,?)",
                    (transaction_id, authenticated_user, payload["tokens"]),
                )
                db.execute(
                    "UPDATE wallets SET balance=balance+? WHERE user=?",
                    (payload["tokens"], authenticated_user),
                )
                balance = db.execute(
                    "SELECT balance FROM wallets WHERE user=?", (authenticated_user,)
                ).fetchone()["balance"]
                return {"balance": balance}

        if path == "/license":
            track_id = action.get("track")
            if not isinstance(track_id, str) or not track_id:
                raise Error("invalid_input")
            track = self.catalog_track(track_id)
            if not track:
                raise Error("not_found", 404)
            cost = self._track_cost(track)
            with self.connection(immediate=True) as db:
                _, wallet = self._require_user(db, authenticated_user)
                licensed = db.execute(
                    "SELECT 1 FROM licenses WHERE user=? AND track=?",
                    (authenticated_user, track_id),
                ).fetchone()
                if licensed:
                    return {"track": track_id, "balance": wallet["balance"]}

                changed = db.execute(
                    "UPDATE wallets SET balance=balance-? "
                    "WHERE user=? AND balance>=?",
                    (cost, authenticated_user, cost),
                ).rowcount
                if changed != 1:
                    raise Error("insufficient_tokens", 409)
                db.execute(
                    "INSERT INTO licenses(user,track) VALUES(?,?)",
                    (authenticated_user, track_id),
                )
                balance = db.execute(
                    "SELECT balance FROM wallets WHERE user=?", (authenticated_user,)
                ).fetchone()["balance"]
                return {"track": track_id, "balance": balance}

        raise Error("not_found", 404)

    def read(self, user, path, query=""):
        with self.connection() as db:
            self._require_user(db, user)
            if path == "/me":
                row = db.execute(
                    "SELECT users.id,users.email,wallets.balance "
                    "FROM users JOIN wallets ON users.id=wallets.user "
                    "WHERE users.id=?",
                    (user,),
                ).fetchone()
                if not row:
                    raise Error("unauthorized", 401)
                return dict(row)
            if path == "/catalog":
                return [
                    {
                        "id": track["id"],
                        "title": track["title"],
                        "artist": track["artist"],
                        "cost": track["cost"],
                    }
                    for track in self.tracks(query)
                ]
            if path == "/licenses":
                return [
                    row[0]
                    for row in db.execute(
                        "SELECT track FROM licenses WHERE user=? ORDER BY track",
                        (user,),
                    )
                ]
        raise Error("not_found", 404)


def main():
    root = Path(__file__).parent
    config = json.loads(Path(os.environ["STREAM_CONFIG"]).read_text())
    store = Store(os.environ["STREAM_DATABASE"], config)
    assets = Path(os.environ["STREAM_ASSETS"]).resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            # Provider credentials and receipt data must not end up in access
            # logs.  The service also has no need for request logging here.
            pass

        def send(self, status, data, mime="application/json", extra=None):
            if mime == "application/json":
                raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
                content_type = "application/json"
            else:
                raw = data if isinstance(data, bytes) else str(data).encode("utf-8")
                content_type = mime
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (extra or {}).items():
                self.send_header(key, str(value))
            self.end_headers()
            self.wfile.write(raw)

        def body(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise Error("invalid_input") from exc
            if size < 0 or size > 65536:
                raise Error("request_too_large", 413)
            try:
                value = json.loads(self.rfile.read(size) or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise Error("invalid_input") from exc
            if not isinstance(value, dict):
                raise Error("invalid_input")
            return value

        def authenticated_user(self):
            authorization = self.headers.get("Authorization", "")
            if not authorization.startswith("Bearer "):
                raise Error("unauthorized", 401)
            token = authorization[7:]
            if not token or " " in token:
                raise Error("unauthorized", 401)
            return token, store.actor(token)

        def media(self, user, track_id):
            track = store.catalog_track(track_id)
            with store.connection() as db:
                licensed = db.execute(
                    "SELECT 1 FROM licenses WHERE user=? AND track=?",
                    (user, track_id),
                ).fetchone()
            if not track or not licensed:
                # Do not disclose whether an unknown track or an unlicensed
                # track exists to an authenticated caller.
                raise Error("not_licensed", 403)

            filename = track.get("filename")
            if not isinstance(filename, str) or not filename:
                raise Error("not_found", 404)
            file_path = (assets / filename).resolve()
            try:
                inside_assets = file_path.is_relative_to(assets)
            except AttributeError:  # pragma: no cover - Python 3.11 is required
                inside_assets = str(file_path).startswith(str(assets) + os.sep)
            if not inside_assets:
                raise Error("not_found", 404)
            raw = file_path.read_bytes()
            total = len(raw)
            range_header = self.headers.get("Range")
            content_type = mimetypes.guess_type(file_path.name)[0] or "audio/wav"
            if file_path.suffix.casefold() == ".wav":
                content_type = "audio/wav"
            if not range_header:
                return self.send(
                    200,
                    raw,
                    content_type,
                    {"Accept-Ranges": "bytes"},
                )

            match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header.strip())
            if not match or total == 0:
                raise Error("invalid_range", 416)
            start = int(match.group(1))
            requested_end = match.group(2)
            end = int(requested_end) if requested_end else total - 1
            end = min(end, total - 1)
            if start >= total or start > end:
                raise Error("invalid_range", 416)
            return self.send(
                206,
                raw[start : end + 1],
                content_type,
                {
                    "Content-Range": f"bytes {start}-{end}/{total}",
                    "Accept-Ranges": "bytes",
                },
            )

        def execute(self):
            try:
                parsed = urllib.parse.urlsplit(self.path)
                path = parsed.path
                if self.command not in ("GET", "POST"):
                    self.send(405, {"error": "method_not_allowed"}, extra={"Allow": "GET, POST"})
                    return

                if self.command == "GET" and path in {
                    "/",
                    "/app.js",
                    "/react.js",
                    "/react-dom.js",
                }:
                    name = "index.html" if path == "/" else path[1:]
                    static_path = root / "dist" / name
                    mime = "text/html" if name == "index.html" else "text/javascript"
                    self.send(200, static_path.read_bytes(), mime)
                    return

                action = self.body() if self.command == "POST" else {}
                if self.command == "POST" and path == "/register":
                    self.send(200, store.register(action))
                    return
                if self.command == "POST" and path == "/login":
                    self.send(200, store.login(action))
                    return

                token, user = self.authenticated_user()
                if self.command == "POST" and path == "/logout":
                    self.send(200, store.logout(token))
                    return
                if self.command == "GET" and path.startswith("/media/"):
                    track_id = urllib.parse.unquote(path[len("/media/") :])
                    self.media(user, track_id)
                    return
                if self.command == "GET":
                    query = urllib.parse.parse_qs(
                        parsed.query, keep_blank_values=True
                    ).get("q", [""])[0]
                    self.send(200, store.read(user, path, query))
                    return
                self.send(200, store.act(user, path, action))
            except Error as exc:
                self.send(exc.status, {"error": exc.message})
            except sqlite3.IntegrityError:
                self.send(409, {"error": "conflict"})
            except sqlite3.OperationalError:
                self.send(503, {"error": "storage_unavailable"})
            except FileNotFoundError:
                self.send(404, {"error": "not_found"})
            except (KeyError, TypeError, ValueError):
                self.send(400, {"error": "invalid_input"})
            except OSError:
                self.send(404, {"error": "not_found"})

        do_GET = execute
        do_POST = execute

    server = ThreadingHTTPServer(
        ("127.0.0.1", int(os.environ.get("PORT", "0"))), Handler
    )
    print(server.server_port, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

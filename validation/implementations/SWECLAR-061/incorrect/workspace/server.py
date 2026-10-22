"""Small, self-contained content-report SaaS service.

The application deliberately keeps the local protocol simple: account data,
sessions, report relationships, and normalized image bytes live in SQLite.  The
HTTP layer is only an adapter around :class:`Store`; the same Store methods are
also useful to the local integration tests.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


MAX_REQUEST_BYTES = 7_000_000
MAX_IMAGE_BYTES = 5_000_000


class Error(Exception):
    """An expected application error that can be returned to an HTTP client."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class Store:
    """Persistent account, report, asset, and local-payment storage."""

    def __init__(self, path: str | os.PathLike[str], config: dict[str, Any]):
        self.path = os.fspath(path)
        self.config = config
        self._memory_connection: sqlite3.Connection | None = None
        if self.path == ":memory:":
            self._memory_connection = sqlite3.connect(":memory:", check_same_thread=False)

        # The benchmark normally creates the runtime directory.  Creating the
        # parent here also makes the service useful when started by hand.
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)

        with self.db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users(
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    salt TEXT NOT NULL,
                    verifier TEXT NOT NULL,
                    trial INTEGER NOT NULL DEFAULT 0,
                    plan TEXT
                );
                CREATE TABLE IF NOT EXISTS sessions(
                    hash TEXT PRIMARY KEY,
                    user TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS payments(
                    id TEXT PRIMARY KEY,
                    user TEXT NOT NULL,
                    plan TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rooms(
                    id TEXT PRIMARY KEY,
                    user TEXT NOT NULL,
                    name TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS content(
                    id TEXT PRIMARY KEY,
                    room TEXT NOT NULL,
                    title TEXT NOT NULL,
                    details TEXT NOT NULL,
                    complete INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS assets(
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    data BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user);
                CREATE INDEX IF NOT EXISTS rooms_user_idx ON rooms(user);
                CREATE INDEX IF NOT EXISTS content_room_idx ON content(room);
                CREATE INDEX IF NOT EXISTS assets_content_idx ON assets(content);
                """
            )

    def db(self) -> sqlite3.Connection:
        """Open a short-lived SQLite connection with row-shaped results."""

        if self._memory_connection is not None:
            db = self._memory_connection
        else:
            db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 10000")
        return db

    def verifier(self, password: str, salt: str) -> str:
        """Return the public scrypt password verifier for a hex salt."""

        return hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt),
            n=16384,
            r=8,
            p=1,
        ).hex()

    @staticmethod
    def _normal_email(value: Any) -> str:
        if not isinstance(value, str):
            raise Error("invalid_credentials")
        email = value.strip().lower()
        # This is intentionally modest validation.  The service needs a stable
        # account key, not a full RFC mail parser, while retaining the starter
        # application's useful rejection of obviously invalid addresses.
        if not email or "@" not in email:
            raise Error("invalid_credentials")
        return email

    @staticmethod
    def _password(value: Any) -> str:
        if not isinstance(value, str) or len(value) < 8:
            raise Error("invalid_credentials")
        return value

    @staticmethod
    def _identifier(value: Any, message: str = "invalid_input") -> str:
        if not isinstance(value, str) or not value.strip():
            raise Error(message)
        return value

    @staticmethod
    def _required_text(value: Any, message: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise Error(message)
        return value

    @staticmethod
    def _account_id(user: Any) -> str:
        try:
            user_id = user["id"]
        except (KeyError, IndexError, TypeError):
            raise Error("unauthorized", 401) from None
        if not isinstance(user_id, str):
            raise Error("unauthorized", 401)
        return user_id

    @staticmethod
    def _public_account(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "email": row["email"],
            "trial": row["trial"],
            "plan": row["plan"],
        }

    def _account_row(self, db: sqlite3.Connection, user: dict[str, Any]) -> sqlite3.Row:
        user_id = self._account_id(user)
        row = db.execute(
            "SELECT id,email,trial,plan FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if row is None:
            raise Error("unauthorized", 401)
        return row

    @staticmethod
    def _has_access(account: sqlite3.Row | dict[str, Any]) -> bool:
        return bool(account["trial"] or account["plan"])

    def auth(self, path: str, action: dict[str, Any]) -> dict[str, str]:
        """Register or log in and create a server-side session."""

        if path not in ("/register", "/login"):
            raise Error("not_found", 404)
        if not isinstance(action, dict):
            raise Error("invalid_input")

        email = self._normal_email(action.get("email"))
        password = self._password(action.get("password"))

        with self.db() as db:
            if path == "/register":
                if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                    raise Error("account_exists", 409)
                ident = secrets.token_hex(12)
                salt = secrets.token_hex(16)
                try:
                    db.execute(
                        "INSERT INTO users(id,email,salt,verifier) VALUES(?,?,?,?)",
                        (ident, email, salt, self.verifier(password, salt)),
                    )
                except sqlite3.IntegrityError as exc:
                    # The explicit lookup above gives a useful normal path;
                    # this handles a concurrent registration race as well.
                    raise Error("account_exists", 409) from exc

            account = db.execute(
                "SELECT id,email,salt,verifier FROM users WHERE email=?", (email,)
            ).fetchone()
            if account is None or not secrets.compare_digest(
                account["verifier"], self.verifier(password, account["salt"])
            ):
                raise Error("invalid_credentials", 401)

            token = secrets.token_urlsafe(32)
            db.execute(
                "INSERT INTO sessions(hash,user) VALUES(?,?)",
                (hashlib.sha256(token.encode()).hexdigest(), account["id"]),
            )
            return {"token": token, "id": account["id"]}

    def user(self, token: str) -> dict[str, Any]:
        """Resolve an untrusted bearer token to the server-owned account."""

        if not isinstance(token, str) or not token:
            raise Error("unauthorized", 401)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.db() as db:
            row = db.execute(
                """
                SELECT u.id,u.email,u.trial,u.plan
                FROM users AS u JOIN sessions AS s ON s.user=u.id
                WHERE s.hash=?
                """,
                (token_hash,),
            ).fetchone()
        if row is None:
            raise Error("unauthorized", 401)
        return dict(row)

    def revoke(self, token: str) -> None:
        """Revoke exactly one session token."""

        if not isinstance(token, str) or not token:
            raise Error("unauthorized", 401)
        with self.db() as db:
            db.execute(
                "DELETE FROM sessions WHERE hash=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )

    def owner(
        self, db: sqlite3.Connection, user: dict[str, Any], content_id: str
    ) -> dict[str, Any]:
        """Return a content row only when it belongs to the given account."""

        user_id = self._account_id(user)
        row = db.execute(
            """
            SELECT c.*,r.user,r.name AS room_name
            FROM content AS c JOIN rooms AS r ON c.room=r.id
            WHERE c.id=?
            """,
            (content_id,),
        ).fetchone()
        if row is None or row["user"] != user_id:
            # Do not disclose whether another account owns the record.
            raise Error("not_found", 404)
        return dict(row)

    def _receipt(self, payment_id: str) -> dict[str, Any]:
        """Fetch and cryptographically verify a local-provider receipt."""

        provider = self.config.get("provider")
        if not isinstance(provider, str) or not provider:
            raise Error("provider_unavailable", 502)
        url = provider.rstrip("/") + "/receipts/" + urllib.parse.quote(
            payment_id, safe=""
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(url, timeout=5) as response:
                raw = response.read(1_000_000)
            receipt = json.loads(raw)
        except urllib.error.HTTPError as exc:
            # A missing or rejected receipt is a bad activation request, not a
            # reason to grant access.
            if exc.code in range(400, 500):
                raise Error("invalid_receipt") from exc
            raise Error("provider_unavailable", 502) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise Error("provider_unavailable", 502) from exc
        except (ValueError, TypeError) as exc:
            raise Error("invalid_receipt") from exc

        if not isinstance(receipt, dict) or not isinstance(
            receipt.get("payload"), dict
        ):
            raise Error("invalid_receipt")
        payload = receipt["payload"]
        signature = receipt.get("signature")
        if not isinstance(signature, str):
            raise Error("invalid_receipt")

        try:
            provider_key = bytes.fromhex(str(self.config["provider_key"]))
            encoded = json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ).encode()
            expected = hmac.new(provider_key, encoded, hashlib.sha256).hexdigest()
        except (KeyError, TypeError, ValueError) as exc:
            raise Error("invalid_receipt") from exc
        if not hmac.compare_digest(expected, signature):
            raise Error("invalid_receipt")
        return payload

    def _activate(
        self,
        db: sqlite3.Connection,
        account: sqlite3.Row,
        action: dict[str, Any],
        user: dict[str, Any],
    ) -> dict[str, Any]:
        payment_id = action.get("payment_id")
        if not isinstance(payment_id, str) or not payment_id:
            raise Error("invalid_receipt")

        payload = self._receipt(payment_id)
        plan_id = payload.get("plan")
        plans = self.config.get("plans")
        plan = plans.get(plan_id) if isinstance(plans, dict) and isinstance(plan_id, str) else None

        def exact_match(actual: Any, expected: Any) -> bool:
            # Python considers True equal to 1; a receipt field must match the
            # configured JSON value, including its basic type.
            return type(actual) is type(expected) and actual == expected

        if (
            not isinstance(plan, dict)
            or "amount" not in plan
            or "currency" not in plan
            or "amount" not in payload
            or "currency" not in payload
            or payload.get("id") != payment_id
            or payload.get("user") != account["id"]
            or payload.get("status") != "paid"
            or not exact_match(payload.get("amount"), plan.get("amount"))
            or not exact_match(payload.get("currency"), plan.get("currency"))
        ):
            raise Error("invalid_receipt")

        # Lock before checking/inserting the idempotency record.  A replay for
        # the same account and plan succeeds without creating another row;
        # using this payment for a different account or plan is rejected.
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute(
            "SELECT id,user,plan FROM payments WHERE id=?", (payment_id,)
        ).fetchone()
        if previous is not None:
            if previous["user"] != account["id"] or previous["plan"] != plan_id:
                raise Error("payment_conflict", 409)
        else:
            try:
                db.execute(
                    "INSERT INTO payments(id,user,plan) VALUES(?,?,?)",
                    (payment_id, account["id"], plan_id),
                )
            except sqlite3.IntegrityError as exc:
                # Normally the transaction lock makes this unnecessary, but a
                # pre-existing database may still expose a concurrent race.
                raise Error("payment_conflict", 409) from exc

        db.execute("UPDATE users SET plan=? WHERE id=?", (plan_id, account["id"]))
        if isinstance(user, dict):
            user["plan"] = plan_id
        return {"plan": plan_id}

    @staticmethod
    def _normalise_image(raw: bytes) -> bytes:
        """Decode an image, apply EXIF orientation, and emit clean JPEG bytes."""

        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("image size")
        with Image.open(BytesIO(raw)) as source:
            source.load()
            oriented = ImageOps.exif_transpose(source)
            rgb = oriented.convert("RGB")
            # Image.convert can carry selected info fields forward.  Clearing
            # them and passing an empty EXIF block prevents private source
            # metadata (EXIF, ICC, comments, and the like) from being copied.
            rgb.info.clear()
            output = BytesIO()
            rgb.save(
                output,
                format="JPEG",
                quality=95,
                optimize=True,
                exif=b"",
            )
            return output.getvalue()

    def act(
        self,
        authenticated_user: dict[str, Any],
        path: str,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply one authenticated documented HTTP action."""

        user = authenticated_user
        if not isinstance(path, str) or not isinstance(action, dict):
            raise Error("invalid_input")

        with self.db() as db:
            account = self._account_row(db, user)
            user_id = account["id"]

            if path == "/trial":
                db.execute("BEGIN IMMEDIATE")
                changed = db.execute(
                    """
                    UPDATE users SET trial=1
                    WHERE id=? AND (plan IS NULL OR plan='')
                    """,
                    (user_id,),
                ).rowcount
                if not changed:
                    raise Error("trial_unavailable", 409)
                if isinstance(user, dict):
                    user["trial"] = 1
                return {"trial": True}

            if path == "/activate":
                return self._activate(db, account, action, user)

            if path not in {
                "/rooms",
                "/content",
                "/edit",
                "/complete",
                "/assets",
                "/share",
            }:
                raise Error("not_found", 404)

            if not self._has_access(account):
                raise Error("access_required", 403)

            if path == "/rooms":
                room_id = self._identifier(action.get("id"))
                name = self._required_text(action.get("name"), "name_required")
                try:
                    db.execute(
                        "INSERT INTO rooms(id,user,name) VALUES(?,?,?)",
                        (room_id, user_id, name),
                    )
                except sqlite3.IntegrityError as exc:
                    raise Error("conflict", 409) from exc
                return {"id": room_id}

            if path == "/content":
                content_id = self._identifier(action.get("id"))
                room_id = self._identifier(action.get("room"), "room_required")
                title = self._required_text(action.get("title"), "details_required")
                details = self._required_text(
                    action.get("details"), "details_required"
                )
                room = db.execute(
                    "SELECT id FROM rooms WHERE id=? AND user=?", (room_id, user_id)
                ).fetchone()
                if room is None:
                    raise Error("room_required")
                try:
                    db.execute(
                        """
                        INSERT INTO content(id,room,title,details)
                        VALUES(?,?,?,?)
                        """,
                        (content_id, room_id, title, details),
                    )
                except sqlite3.IntegrityError as exc:
                    raise Error("conflict", 409) from exc
                return {"id": content_id}

            if path == "/edit":
                content_id = self._identifier(action.get("id"))
                self.owner(db, user, content_id)
                title = self._required_text(action.get("title"), "details_required")
                details = self._required_text(
                    action.get("details"), "details_required"
                )
                db.execute(
                    "UPDATE content SET title=?,details=? WHERE id=?",
                    (title, details, content_id),
                )
                return {"id": content_id}

            if path == "/complete":
                content_id = self._identifier(action.get("id"))
                self.owner(db, user, content_id)
                db.execute("UPDATE content SET complete=1 WHERE id=?", (content_id,))
                return {"id": content_id}

            if path == "/assets":
                asset_id = self._identifier(action.get("id"))
                content_id = self._identifier(action.get("content"))
                self.owner(db, user, content_id)
                kind = action.get("kind")
                if kind not in ("image", "receipt"):
                    raise Error("invalid_kind")
                encoded = action.get("data")
                if not isinstance(encoded, str):
                    raise Error("invalid_image")
                try:
                    raw = base64.b64decode(encoded, validate=True)
                    jpeg = self._normalise_image(raw)
                except Exception as exc:
                    # Pillow raises several format-specific exceptions.  They
                    # are all one invalid uploaded file from the API's point of
                    # view; never persist a partial asset.
                    raise Error("invalid_image") from exc
                try:
                    db.execute(
                        "INSERT INTO assets(id,content,kind,data) VALUES(?,?,?,?)",
                        (asset_id, content_id, kind, sqlite3.Binary(jpeg)),
                    )
                except sqlite3.IntegrityError as exc:
                    raise Error("conflict", 409) from exc
                return {"id": asset_id}

            # The caller must own the report before the entitlement check so a
            # foreign report cannot be used to probe plan state or content.
            content_id = self._identifier(action.get("id"))
            row = self.owner(db, user, content_id)
            if not account["plan"]:
                raise Error("paid_plan_required", 403)
            # Downloadable sharing is intentionally only a local copy; it does
            # not publish the report or contact an external service.
            return {
                "content": row["id"],
                "title": row["title"],
                "details": row["details"],
            }

    def _pdf(self, db: sqlite3.Connection, row: dict[str, Any]) -> bytes:
        """Build a real printable PDF containing report text and stored images."""

        output = BytesIO()
        document = canvas.Canvas(output, pagesize=letter)
        document.setTitle("Synthetic content report")

        # DejaVu is available in the supplied Python image; use a standard font
        # fallback for installations that do not have system fonts.  A TTF
        # avoids failures when a legitimate report contains non-ASCII text.
        font = "Helvetica"
        bold_font = "Helvetica-Bold"
        regular_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        try:
            if "ReportSans" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("ReportSans", regular_path))
            if "ReportSans-Bold" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("ReportSans-Bold", bold_path))
            font = "ReportSans"
            bold_font = "ReportSans-Bold"
        except Exception:
            # Font registration is a convenience; the standard PDF fonts still
            # produce a valid export on systems without the bundled TTF files.
            font = "Helvetica"
            bold_font = "Helvetica-Bold"

        left = 48
        top = 752
        bottom = 48
        width = letter[0] - 96
        y = top

        def set_body() -> None:
            document.setFont(font, 10)

        def new_page() -> None:
            nonlocal y
            document.showPage()
            y = top
            set_body()

        document.setFont(bold_font, 18)
        title_lines = textwrap.wrap(
            str(row["title"]), width=70, break_long_words=True, break_on_hyphens=False
        ) or [""]
        for line in title_lines:
            if y < bottom + 24:
                new_page()
                document.setFont(bold_font, 18)
            document.drawString(left, y, line)
            y -= 25

        set_body()
        y -= 4
        details_lines = textwrap.wrap(
            str(row["details"]),
            width=95,
            break_long_words=True,
            break_on_hyphens=False,
        ) or [""]
        for line in details_lines:
            if y < bottom:
                new_page()
            document.drawString(left, y, line)
            y -= 15

        assets = db.execute(
            "SELECT kind,data FROM assets WHERE content=? ORDER BY id", (row["id"],)
        ).fetchall()
        for asset in assets:
            try:
                image = ImageReader(BytesIO(bytes(asset["data"])))
                image_width, image_height = image.getSize()
                if not image_width or not image_height:
                    continue
                max_width = width
                max_height = 270
                scale = min(max_width / image_width, max_height / image_height, 1.0)
                draw_width = image_width * scale
                draw_height = image_height * scale
                if y - draw_height - 20 < bottom:
                    new_page()
                document.setFont(font, 9)
                document.drawString(left, y, str(asset["kind"]).title())
                y -= 12
                document.drawImage(
                    image,
                    left,
                    y - draw_height,
                    width=draw_width,
                    height=draw_height,
                    preserveAspectRatio=True,
                    mask="auto",
                )
                y -= draw_height + 18
                set_body()
            except Exception:
                # An asset should already be a valid normalized JPEG.  If an
                # old database contains a damaged blob, still produce the text
                # report rather than failing the paid export altogether.
                continue

        document.save()
        return output.getvalue()

    def read(self, user: dict[str, Any], path: str) -> Any:
        """Read one documented authenticated resource."""

        if not isinstance(path, str):
            raise Error("not_found", 404)
        with self.db() as db:
            account = self._account_row(db, user)
            if path == "/me":
                result = self._public_account(account)
                if isinstance(user, dict):
                    user.update(result)
                return result

            if path == "/rooms":
                return [
                    dict(row)
                    for row in db.execute(
                        "SELECT id,name FROM rooms WHERE user=? ORDER BY id",
                        (account["id"],),
                    )
                ]

            if path == "/content":
                return [
                    dict(row)
                    for row in db.execute(
                        """
                        SELECT c.id,c.room,c.title,c.details,c.complete
                        FROM content AS c JOIN rooms AS r ON r.id=c.room
                        WHERE r.user=? ORDER BY c.id
                        """,
                        (account["id"],),
                    )
                ]

            if path.startswith("/assets/"):
                asset_id = path[len("/assets/") :]
                if not asset_id or "/" in asset_id:
                    raise Error("not_found", 404)
                row = db.execute(
                    "SELECT id,content,data FROM assets WHERE id=?", (asset_id,)
                ).fetchone()
                if row is None:
                    raise Error("not_found", 404)
                self.owner(db, user, row["content"])
                return bytes(row["data"]), "image/jpeg"

            if path.startswith("/report/"):
                content_id = path[len("/report/") :]
                if not content_id or "/" in content_id:
                    raise Error("not_found", 404)
                row = self.owner(db, user, content_id)
                row["assets"] = [
                    dict(asset)
                    for asset in db.execute(
                        "SELECT id,kind FROM assets WHERE content=? ORDER BY id",
                        (content_id,),
                    )
                ]
                return row

            if path.startswith("/export/"):
                content_id = path[len("/export/") :]
                if not content_id or "/" in content_id:
                    raise Error("not_found", 404)
                row = self.owner(db, user, content_id)
                if not account["plan"]:
                    # Trial access intentionally stops at viewing/editing.
                    raise Error("paid_plan_required", 403)
                return self._pdf(db, row), "application/pdf"

            raise Error("not_found", 404)


def main() -> None:
    root = Path(__file__).parent
    config_path = os.environ.get("SAAS_CONFIG")
    database_path = os.environ.get("SAAS_DATABASE")
    if not config_path or not database_path:
        raise SystemExit("SAAS_CONFIG and SAAS_DATABASE are required")
    config = json.loads(Path(config_path).read_text())
    store = Store(database_path, config)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            # The port on stdout is the startup protocol; normal request logs
            # are intentionally quiet so browser smoke tests can read it.
            return

        def send_data(self, status: int, data: Any) -> None:
            mime = "application/json"
            if isinstance(data, tuple):
                data, mime = data
            if isinstance(data, str):
                data = data.encode()
            elif not isinstance(data, (bytes, bytearray)):
                data = json.dumps(data, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def execute(self) -> None:
            try:
                path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
                if self.command == "GET" and path in ("/", "/app.js", "/style.css"):
                    filename = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}[path]
                    mime = {
                        "/": "text/html; charset=utf-8",
                        "/app.js": "text/javascript; charset=utf-8",
                        "/style.css": "text/css; charset=utf-8",
                    }[path]
                    return self.send_data(200, (root.joinpath(filename).read_bytes(), mime))

                if self.command != "GET":
                    try:
                        size = int(self.headers.get("Content-Length", "0"))
                    except ValueError as exc:
                        raise Error("invalid_input") from exc
                    if size < 0:
                        raise Error("invalid_input")
                    if size > MAX_REQUEST_BYTES:
                        raise Error("request_too_large", 413)
                    try:
                        action = json.loads(self.rfile.read(size) or b"{}")
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise Error("invalid_input") from exc
                    if not isinstance(action, dict):
                        raise Error("invalid_input")
                else:
                    action = {}

                if self.command == "POST" and path in ("/register", "/login"):
                    return self.send_data(200, store.auth(path, action))

                authorization = self.headers.get("Authorization", "")
                token = authorization[7:] if authorization.startswith("Bearer ") else ""
                user = store.user(token)

                if self.command == "POST" and path == "/logout":
                    store.revoke(token)
                    return self.send_data(200, {})

                if self.command == "GET":
                    return self.send_data(200, store.read(user, path))
                if self.command == "POST":
                    return self.send_data(200, store.act(user, path, action))
                raise Error("method_not_allowed", 405)
            except Error as exc:
                self.send_data(exc.status, {"error": exc.message})
            except sqlite3.IntegrityError:
                self.send_data(409, {"error": "conflict"})
            except (KeyError, TypeError, ValueError):
                self.send_data(400, {"error": "invalid_input"})

        do_GET = execute
        do_POST = execute
        do_PUT = execute
        do_PATCH = execute
        do_DELETE = execute

    server = ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "0"))), Handler)
    print(server.server_port, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

"""Loopback-only HTTP shell for the offline map console."""

from __future__ import annotations

from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import mimetypes
import os
import urllib.parse

from store import Store


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("CONSOLE_CONFIG", "config.json"))
DATABASE_PATH = os.environ.get("CONSOLE_DATABASE", "sessions.sqlite")
ASSET_ROOT = Path(
    os.environ.get("CESIUM_ASSET_DIR", "/opt/sweclar/cesium/Build/Cesium")
).resolve()

with CONFIG_PATH.open(encoding="utf-8") as config_file:
    CONFIG = json.load(config_file)
store = Store(DATABASE_PATH, CONFIG)

PUBLIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    """Serve only the page, the designated Cesium tree, and local APIs."""

    # The application never needs reverse-DNS lookups for request logging.
    def log_message(self, *_args: object) -> None:
        pass

    def token(self) -> str | None:
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        morsel = cookies.get("session")
        return morsel.value if morsel is not None else None

    def send(
        self,
        status: int,
        data: object,
        mime: str = "application/json; charset=utf-8",
        token: str | None = None,
    ) -> None:
        if isinstance(data, bytes):
            payload = data
        elif mime.startswith("application/json"):
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        else:
            payload = bytes(data) if isinstance(data, bytearray) else data
            if not isinstance(payload, bytes):
                payload = str(payload).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if mime.startswith("application/json"):
            self.send_header("Cache-Control", "no-store")
        if token is not None:
            cookie = SimpleCookie()
            cookie["session"] = token
            cookie["session"]["path"] = "/"
            cookie["session"]["httponly"] = True
            cookie["session"]["samesite"] = "Strict"
            if token == "":
                cookie["session"]["max-age"] = 0
                cookie["session"]["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
            self.send_header("Set-Cookie", cookie.output(header="").strip())
        self.end_headers()
        self.wfile.write(payload)

    def local_file(self, request_path: str) -> Path | None:
        """Resolve a Cesium URL without allowing traversal outside its root."""

        relative = urllib.parse.unquote(request_path.removeprefix("/cesium/"))
        candidate = (ASSET_ROOT / relative).resolve()
        if not candidate.is_relative_to(ASSET_ROOT) or not candidate.is_file():
            return None
        return candidate

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query, keep_blank_values=True)
        try:
            if url.path in PUBLIC_FILES:
                filename, mime = PUBLIC_FILES[url.path]
                return self.send(200, (ROOT / filename).read_bytes(), mime)

            if url.path.startswith("/cesium/"):
                file_path = self.local_file(url.path)
                if file_path is None:
                    return self.send(404, {})
                return self.send(
                    200,
                    file_path.read_bytes(),
                    mimetypes.guess_type(str(file_path))[0]
                    or "application/octet-stream",
                )

            user = store.actor(self.token())
            if url.path == "/me":
                return self.send(200, user)
            if url.path == "/locations":
                return self.send(200, store.locations(query.get("q", [""])[0]))
            if url.path == "/tracks":
                return self.send(200, store.tracks())
            if url.path == "/rewind":
                return self.send(
                    200,
                    store.rewind(
                        query.get("id", [""])[0],
                        query.get("at", [""])[0],
                    ),
                )
            return self.send(404, {})
        except PermissionError:
            return self.send(403, {"error": "login_required"})
        except LookupError:
            return self.send(404, {"error": "not_found"})
        except Exception:
            # Do not turn private configuration or implementation details into
            # an API response.  Invalid client input has one public shape.
            return self.send(400, {"error": "request_failed"})

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path = urllib.parse.urlsplit(self.path).path
        try:
            raw_length = self.headers.get("Content-Length", "0")
            length = int(raw_length)
            if length < 0 or length > 10000:
                raise ValueError("size")
            body = self.rfile.read(length) if length else b""

            # Sign-out is intentionally usable with an empty body.  Revoking
            # the server-side hash is what matters; the cookie is cleared too.
            if path == "/logout":
                store.logout(self.token())
                return self.send(200, {"logged_out": True}, token="")

            if path != "/login" or not body:
                return self.send(404, {}) if path != "/login" else self.send(
                    400, {"error": "request_failed"}
                )
            credentials = json.loads(body)
            if not isinstance(credentials, dict):
                raise ValueError("body")
            token, user = store.login(credentials)
            return self.send(200, user, token=token)
        except PermissionError:
            return self.send(403, {"error": "invalid_login"})
        except Exception:
            return self.send(400, {"error": "request_failed"})


def main() -> None:
    port = int(os.environ.get("PORT", "0"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    print(json.dumps({"port": server.server_port}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

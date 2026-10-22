from __future__ import annotations

import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from store import Store


ROOT = Path(__file__).parent
config = json.loads(Path(os.environ["FOOD_CONFIG"]).read_text(encoding="utf-8"))
store = Store(os.environ["FOOD_DATABASE"], config)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: Any) -> None:
        # The test runner uses stdout for the machine-readable port line.
        pass

    def send(self, status: int, data: Any, mime: str = "application/json") -> None:
        if not isinstance(data, bytes):
            data = json.dumps(data, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def actor(self) -> str:
        header = self.headers.get("Authorization", "")
        parts = header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise PermissionError("denied")
        return store.actor(parts[1])

    @staticmethod
    def _static_files() -> dict[str, tuple[str, str]]:
        return {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
            "/vendor/leaflet.js": ("vendor/leaflet.js", "text/javascript; charset=utf-8"),
            "/vendor/leaflet.css": ("vendor/leaflet.css", "text/css; charset=utf-8"),
        }

    def do_GET(self) -> None:
        request = urllib.parse.urlsplit(self.path)
        files = self._static_files()
        try:
            if request.path in files:
                filename, mime = files[request.path]
                return self.send(200, (ROOT / filename).read_bytes(), mime)

            user = self.actor()
            if request.path == "/feed":
                return self.send(200, store.feed(user))
            if request.path == "/venues":
                # The configuration is the independent synthetic venue catalog;
                # do not expose any other configuration keys to the browser.
                venues = config.get("venues", {})
                return self.send(200, venues if isinstance(venues, dict) else {})
            if request.path == "/pins":
                params = urllib.parse.parse_qs(
                    request.query, keep_blank_values=True
                )
                mode_values = params.get("mode")
                # Personal is the supplied component's default when the query
                # parameter is omitted; an explicitly blank/ambiguous value is
                # still invalid rather than silently changing scope.
                if mode_values is None:
                    mode = "personal"
                elif len(mode_values) != 1 or not mode_values[0]:
                    raise ValueError("map_mode")
                else:
                    mode = mode_values[0]
                return self.send(200, store.pins(user, mode))
            if request.path.startswith("/image/"):
                # This value is used only as a parameterized SQLite key.  It is
                # never joined to ROOT or interpreted as a filesystem path.
                ident = urllib.parse.unquote(request.path[len("/image/") :])
                return self.send(200, store.image(user, ident), "image/png")
            return self.send(404, {})
        except PermissionError:
            self.send(403, {"error": "denied"})
        except Exception:
            self.send(400, {"error": "request_failed"})

    def _json_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError) as exc:
            raise ValueError("size") from exc
        # Uploads are encoded in JSON, so allow comfortably more than a small
        # camera photo while retaining a bounded request body.
        if not 0 < length <= 15_000_000:
            raise ValueError("size")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError("body")
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("body")
        return body

    def do_POST(self) -> None:
        try:
            user = self.actor()
            body = self._json_body()
            path = urllib.parse.urlsplit(self.path).path
            method = {
                "/upload": store.upload,
                "/post": store.post,
                "/save": store.save,
            }.get(path)
            if method is None:
                return self.send(404, {})
            self.send(200, method(user, body))
        except PermissionError:
            self.send(403, {"error": "denied"})
        except Exception:
            self.send(400, {"error": "request_failed"})


server = ThreadingHTTPServer(
    ("127.0.0.1", int(os.environ.get("PORT", "0"))), Handler
)
print(json.dumps({"port": server.server_port}), flush=True)
server.serve_forever()

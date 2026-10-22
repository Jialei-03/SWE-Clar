"""Local HTTP transport for the catalogue component.

Only the small browser shell is public.  API and image requests require a
bearer token resolved by Store from the private runtime configuration; source
files and that configuration are never exposed as a filesystem server.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
from urllib.parse import unquote, urlsplit

from store import Store


ROOT = Path(__file__).parent
_config_path = os.environ.get("KIOSK_CONFIG")
_database_path = os.environ.get("KIOSK_DATABASE")
if not _config_path or not _database_path:
    raise RuntimeError("KIOSK_CONFIG and KIOSK_DATABASE are required")
config = json.loads(Path(_config_path).read_text(encoding="utf-8"))
store = Store(_database_path, config)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        # Do not put bearer tokens or request paths into the demo's output.
        pass

    def send(self, status: int, data, mime: str = "application/json"):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store" if mime == "application/json" else "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def actor(self):
        header = self.headers.get("Authorization", "")
        if not isinstance(header, str) or not header.startswith("Bearer "):
            raise PermissionError("denied")
        token = header[len("Bearer ") :]
        if not token or token != token.strip() or "\r" in token or "\n" in token:
            raise PermissionError("denied")
        return store.actor(token)

    def do_GET(self):
        request_path = urlsplit(self.path).path
        # The browser shell is the only unauthenticated material.  There is no
        # generic directory or source-file serving route here.
        static = {
            "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
        }
        if request_path in static:
            name, mime = static[request_path]
            try:
                return self.send(200, (ROOT / name).read_bytes(), mime)
            except OSError:
                return self.send(404, {})

        try:
            actor = self.actor()
            if request_path == "/snapshot":
                return self.send(200, store.snapshot(actor))

            if request_path.startswith("/asset/"):
                # Decode the configured ID.  It is looked up in the latest
                # publication before the private path is read.
                encoded_id = request_path[len("/asset/") :]
                if not encoded_id:
                    return self.send(404, {})
                asset_id = unquote(encoded_id)
                if not asset_id:
                    return self.send(404, {})
                try:
                    data = store.asset_bytes(actor, asset_id)
                except KeyError:
                    return self.send(404, {})
                return self.send(200, data, "image/svg+xml")

            if request_path == "/analytics":
                return self.send(200, store.analytics(actor))

            return self.send(404, {})
        except PermissionError:
            return self.send(403, {"error": "denied"})
        except Exception:
            # Never disclose configuration paths, SQL, or bridge details over
            # the HTTP boundary.
            return self.send(400, {"error": "request_failed"})

    def do_POST(self):
        try:
            actor = self.actor()
            raw_length = self.headers.get("Content-Length", "")
            try:
                length = int(raw_length)
            except (TypeError, ValueError):
                raise ValueError("size")
            if not 0 < length <= 100000:
                raise ValueError("size")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("body")
            try:
                action = json.loads(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("body") from exc
            if not isinstance(action, dict):
                raise ValueError("body")

            request_path = urlsplit(self.path).path
            methods = {
                "/edit": store.edit,
                "/publish": store.publish,
                "/track": store.track,
                "/settings": store.settings,
            }
            method = methods.get(request_path)
            if method is None:
                return self.send(404, {})
            return self.send(200, method(actor, action))
        except PermissionError:
            return self.send(403, {"error": "denied"})
        except Exception:
            return self.send(400, {"error": "request_failed"})


if __name__ == "__main__":
    server = ThreadingHTTPServer(
        ("127.0.0.1", int(os.environ.get("PORT", "0"))), Handler
    )
    print(json.dumps({"port": server.server_port}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

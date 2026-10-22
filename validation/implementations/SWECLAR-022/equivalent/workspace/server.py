"""Small authenticated HTTP adapter for the loyalty store."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from store import Fault, Store


def invalid_constant(_):
    raise ValueError("Nonfinite JSON")


class Handler(BaseHTTPRequestHandler):
    # The benchmark speaks HTTP/1.1-compatible requests, but keeping the
    # default close behavior avoids stale response/body interactions in simple
    # clients and does not affect the API contract.
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def respond(self, status, value, content_type=None):
        if isinstance(value, bytes):
            raw = value
            content_type = content_type or "image/png"
        else:
            raw = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
            content_type = content_type or "application/json; charset=utf-8"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 800000:
                raise ValueError("length")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("short body")
            body = json.loads(raw.decode("utf-8"), parse_constant=invalid_constant)
            if not isinstance(body, dict):
                raise ValueError("object required")
            return body
        except (ValueError, UnicodeError, json.JSONDecodeError, TypeError, RecursionError):
            raise Fault(400, "invalid_request")

    def process(self):
        try:
            path = urlsplit(self.path).path
            static = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
            }
            if self.command == "GET" and path in static:
                filename, mime = static[path]
                self.respond(200, (Path(__file__).parent / filename).read_bytes(), mime)
                return

            authorization = self.headers.get("Authorization", "")
            token = authorization[7:] if authorization.startswith("Bearer ") else ""
            # Authorization deliberately precedes body parsing: a malformed
            # protected request still has the required 401/403 semantics.
            self.server.store.authorize(self.command, path, token)
            body = self._body() if self.command in ("POST", "PUT", "PATCH") else {}
            status, result = self.server.store.handle(self.command, path, token, body)
            self.respond(status, result)
        except Fault as error:
            self.respond(error.status, {"error": {"code": error.code}})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            # Do not expose implementation details.  Ordinary malformed
            # requests are handled above; this is only a final containment
            # guard for a damaged local store or transport.
            try:
                self.respond(500, {"error": {"code": "server_error"}})
            except (BrokenPipeError, ConnectionResetError):
                pass

    do_GET = do_POST = do_PUT = do_PATCH = process


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--db", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--clock", required=True)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.store = Store(args.db, args.fixture, args.clock)
    try:
        server.serve_forever()
    finally:
        server.server_close()

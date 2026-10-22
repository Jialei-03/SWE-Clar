"""Standalone local HTTP entry point for the synthetic arena."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit

from arena import Arena, Conflict, reject


ROOT = Path(__file__).resolve().parent


class RequestHandlerFactory:
    """Create a handler class bound to one ephemeral :class:`Arena`."""

    def __init__(self, arena):
        self.arena = arena

    def __call__(self):
        arena = self.arena

        class Handler(BaseHTTPRequestHandler):
            # HTTP/1.0 closes responses by default, which also keeps malformed
            # request bodies from being accidentally interpreted as a next
            # request by this intentionally small service.
            protocol_version = "HTTP/1.0"

            def log_message(self, *_args):
                pass

            def send(self, status, value, content_type="application/json"):
                if content_type == "application/json":
                    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                else:
                    data = value
                self.send_response(status)
                self.send_header("Content-Type", content_type + "; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def read_json_object(self):
                """Read exactly one bounded UTF-8 JSON object body."""
                raw_length = self.headers.get("Content-Length")
                try:
                    # Content-Length is required for every JSON POST in the
                    # public protocol.  bool is not relevant here because the
                    # header value is always text.
                    length = int(raw_length) if raw_length is not None else -1
                except (TypeError, ValueError):
                    reject(400, "invalid_request")
                if length <= 0 or length > 16384:
                    reject(400, "invalid_request")
                raw = self.rfile.read(length)
                if len(raw) != length:
                    reject(400, "invalid_request")
                try:
                    text = raw.decode("utf-8")
                    value = json.loads(
                        text,
                        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
                    )
                except (UnicodeDecodeError, ValueError, TypeError, RecursionError, OverflowError):
                    reject(400, "invalid_request")
                if not isinstance(value, dict):
                    reject(400, "invalid_request")
                return value

            def token(self):
                authorization = self.headers.get("Authorization")
                if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
                    return None
                token = authorization[7:]
                return token if token else None

            def dispatch(self, method):
                try:
                    path = urlsplit(self.path).path

                    # Resolve the route/method before reading a body.  Unknown
                    # paths and wrong methods are always the public 404 shape.
                    post_routes = {"/api/join", "/api/leave", "/api/move", "/api/respawn"}
                    if method == "GET" and path in {"/", "/app.js", "/style.css"}:
                        name = "index.html" if path == "/" else path[1:]
                        mime = {
                            "index.html": "text/html",
                            "app.js": "text/javascript",
                            "style.css": "text/css",
                        }[name]
                        return self.send(200, (ROOT / name).read_bytes(), mime)
                    if method == "GET" and path == "/health":
                        return self.send(200, {"ok": True})
                    if method == "GET" and path == "/api/rooms":
                        return self.send(200, arena.catalog())
                    if method == "GET" and path == "/api/state":
                        return self.send(200, arena.state(self.token()))
                    if method != "POST" or path not in post_routes:
                        reject(404, "not_found")

                    body = self.read_json_object()
                    if path == "/api/join":
                        return self.send(201, arena.join(body))
                    token = self.token()
                    if path == "/api/leave":
                        return self.send(200, arena.leave(token))
                    if path == "/api/move":
                        return self.send(200, arena.command(token, "move", body))
                    if path == "/api/respawn":
                        return self.send(200, arena.command(token, "respawn", body))
                    # Kept for completeness if the route table is extended.
                    reject(404, "not_found")
                except Conflict as exc:
                    self.send(exc.status, {"error": exc.code})
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception:
                    # All business paths are JSON.  Do not expose process or
                    # filesystem details in an unexpected service failure.
                    try:
                        self.send(500, {"error": "service_error"})
                    except (BrokenPipeError, ConnectionResetError):
                        pass

            def do_GET(self):
                self.dispatch("GET")

            def do_POST(self):
                self.dispatch("POST")

            def do_PUT(self):
                self.dispatch("PUT")

            def do_DELETE(self):
                self.dispatch("DELETE")

            def do_PATCH(self):
                self.dispatch("PATCH")

            def do_HEAD(self):
                self.dispatch("HEAD")

            def do_OPTIONS(self):
                self.dispatch("OPTIONS")

            def do_TRACE(self):
                self.dispatch("TRACE")

            def do_CONNECT(self):
                self.dispatch("CONNECT")

        return Handler


def handler(arena):
    return RequestHandlerFactory(arena)()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--world", default="fixtures/world.json")
    parser.add_argument("--clock-file", default="fixtures/clock.json")
    args = parser.parse_args()
    arena = Arena(json.loads(Path(args.world).read_text(encoding="utf-8")), args.clock_file)
    ThreadingHTTPServer((args.host, args.port), handler(arena)).serve_forever()

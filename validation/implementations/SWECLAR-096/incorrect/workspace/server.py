"""Small loopback HTTP service for the browser calculator."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from calculator import calculate
from report import report_pdf


ROOT = Path(__file__).parent / "web"
MAX_BODY_BYTES = 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    """Serve only the documented browser assets and calculation endpoints."""

    # HTTP/1.0 keeps each response self-contained and works well with the
    # simple fetch clients used by the component.
    protocol_version = "HTTP/1.0"

    def log_message(self, *_args):
        # Keep the startup JSON on stdout easy for the launcher to consume.
        pass

    def _send(self, status: int, body, content_type: str = "application/json") -> None:
        if content_type == "application/json":
            data = json.dumps(body, allow_nan=False, separators=(",", ":")).encode("utf-8")
        else:
            data = body if isinstance(body, bytes) else bytes(body)

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if content_type == "application/pdf":
            self.send_header("Content-Disposition", 'attachment; filename="area-report.pdf"')
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def _route(path: str) -> str:
        # Ignore a query string while retaining an exact allowlist of routes.
        return urlsplit(path).path

    def do_GET(self):
        assets = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
        }
        route = self._route(self.path)
        asset = assets.get(route)
        if asset is None:
            self._send(404, {"error": "not_found"})
            return

        filename, content_type = asset
        try:
            body = (ROOT / filename).read_bytes()
        except OSError:
            # This is an internal deployment problem, not a reason to expose a
            # filesystem path or source file in an HTTP response.
            self._send(404, {"error": "not_found"})
            return
        self._send(200, body, content_type)

    def _read_json_body(self):
        header = self.headers.get("Content-Length")
        try:
            size = int(header) if header is not None else 0
        except (TypeError, ValueError):
            raise ValueError("invalid_input") from None

        if size <= 0 or size > MAX_BODY_BYTES:
            raise ValueError("invalid_input")

        body = self.rfile.read(size)
        if len(body) != size:
            raise ValueError("invalid_input")
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            raise ValueError("invalid_input") from None

    def do_POST(self):
        route = self._route(self.path)
        if route not in {"/calculate", "/report"}:
            self._send(404, {"error": "not_found"})
            return

        try:
            values = self._read_json_body()
            calculated = calculate(values)
            if route == "/calculate":
                self._send(200, calculated)
                return

            # report_pdf validates/calculates from this request's values and
            # returns the actual PDF bytes.  No result is kept in shared state.
            self._send(200, report_pdf(values), "application/pdf")
        except (ValueError, TypeError, OverflowError):
            # In particular, do not send a partial JSON result or PDF for an
            # invalid request.
            self._send(400, {"error": "invalid_input"})


class Server(ThreadingHTTPServer):
    request_queue_size = 32


if __name__ == "__main__":
    server = Server(("127.0.0.1", int(os.environ.get("PORT", 0))), Handler)
    print(json.dumps({"port": server.server_port}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

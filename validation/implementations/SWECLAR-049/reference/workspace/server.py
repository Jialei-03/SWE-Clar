import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from solution import process_mentor_event


def _error(code="invalid_event"):
    return {"error": {"code": code or "invalid_event"}}


def _reject_json_constant(value):
    # NaN and Infinity are accepted by Python's decoder by default but are not
    # JSON values.  Treat them as malformed request bodies.
    raise ValueError("invalid JSON constant: " + value)


def serve(database_path, port):
    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status, payload):
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self._send_json(200, {"ok": True})
            else:
                self._send_json(404, _error("not_found"))

        def do_POST(self):
            if self.path != "/events":
                self._send_json(404, _error("not_found"))
                return

            try:
                raw_length = self.headers.get("Content-Length")
                length = int(raw_length) if raw_length is not None else 0
                if length < 0:
                    raise ValueError("invalid content length")
                raw_body = self.rfile.read(length)
                event = json.loads(
                    raw_body, parse_constant=_reject_json_constant
                )
                if not isinstance(event, dict):
                    raise ValueError("object required")
            except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
                self._send_json(400, _error("invalid_event"))
                return

            try:
                result = process_mentor_event(database_path, event)
            except Exception:
                # The function entry point normally converts application errors
                # to an envelope.  Keep the HTTP contract intact even if a
                # filesystem or unexpected server error escapes it.
                result = _error("invalid_state")

            if not isinstance(result, dict) or "error" in result:
                if not isinstance(result, dict) or not isinstance(
                    result.get("error"), dict
                ) or not result["error"].get("code"):
                    result = _error("invalid_state")
                self._send_json(400, result)
            else:
                self._send_json(200, result)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(json.dumps({"port": server.server_port}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    serve(args.db, args.port)

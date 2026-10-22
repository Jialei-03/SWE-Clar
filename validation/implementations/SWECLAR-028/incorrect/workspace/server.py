"""Local scheduling HTTP entrypoint."""

import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from service import signup, tick
from store import connect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as config_file:
        config = json.load(config_file)
    db_path = config["database"]
    sink_url = config["notification_url"]
    timezone = config["timezone"]
    # Initialize the application tables without changing any seeded shifts.
    with connect(db_path):
        pass

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, data):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 - required by BaseHTTPRequestHandler
            if self.path == "/health":
                return self.respond(200, {"ready": True})
            if self.path == "/state":
                with connect(db_path) as db:
                    state = {
                        name: [
                            dict(row)
                            for row in db.execute(f"SELECT * FROM {name}")
                        ]
                        for name in ("employees", "shifts", "signups")
                    }
                return self.respond(200, state)
            return self.respond(404, {"error": "not_found"})

        def do_POST(self):  # noqa: N802 - required by BaseHTTPRequestHandler
            if self.path not in ("/signups", "/tick"):
                return self.respond(404, {"error": "not_found"})
            try:
                raw_length = self.headers.get("Content-Length", "0")
                length = int(raw_length)
                if not 0 < length <= 65536:
                    raise ValueError("invalid_payload")
                data = json.loads(self.rfile.read(length))
                if self.path == "/signups":
                    result = signup(db_path, sink_url, data)
                else:
                    if not isinstance(data, dict) or "now" not in data:
                        raise ValueError("invalid_now")
                    result = tick(db_path, sink_url, data["now"], timezone)
                return self.respond(200, result)
            except (ValueError, KeyError, TypeError, OverflowError, sqlite3.IntegrityError):
                return self.respond(400, {"error": "invalid_request"})
            except (TimeoutError, RuntimeError, OSError):
                # RuntimeError is used by the service for a failed notification
                # delivery.  The persisted signup/stage remains retryable.
                return self.respond(503, {"error": "delivery_unavailable"})

        def log_message(self, *args):
            # The benchmark talks to the service over HTTP and does not need
            # access-log noise on stdout.
            pass

    class Server(ThreadingHTTPServer):
        daemon_threads = True

    Server(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()

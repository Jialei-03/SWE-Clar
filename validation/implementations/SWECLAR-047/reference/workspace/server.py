import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from model import Rejected, apply, host, initial

ROOT = Path(__file__).resolve().parent


def database(path):
    """Open the single-row workspace database and ensure its initial value."""
    connection = sqlite3.connect(path, timeout=30, isolation_level=None)
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS workspace (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT OR IGNORE INTO workspace VALUES (1, ?)",
        (json.dumps(initial(), ensure_ascii=False),),
    )
    return connection


def load(connection):
    row = connection.execute("SELECT payload FROM workspace WHERE id=1").fetchone()
    # The table is owned by this service; this guard makes a damaged database
    # a normal invalid-command response rather than an HTML traceback.
    if row is None:
        raise Rejected("invalid_command")
    return json.loads(row[0])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, status, body, kind="application/json"):
        encoded = body.encode() if isinstance(body, str) else json.dumps(
            body, ensure_ascii=False
        ).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path in ("/api/state", "/api/document"):
            try:
                connection = database(self.server.db)
                try:
                    data = load(connection)
                finally:
                    connection.close()
            except (ValueError, TypeError, KeyError, UnicodeError, sqlite3.Error):
                return self.send(500, {"error": "invalid_command"})
            return self.send(
                200,
                data["state"]
                if self.path == "/api/state"
                else {"nodes": data["document"], "current": data["current"]},
            )

        static = {
            "/": ("index.html", "text/html"),
            "/host.js": ("host.js", "text/javascript"),
            "/sidebar.js": ("sidebar.js", "text/javascript"),
            "/styles.css": ("styles.css", "text/css"),
        }
        if self.path not in static:
            return self.send(404, {"error": "not_found"})
        name, kind = static[self.path]
        try:
            content = (ROOT / name).read_text()
        except OSError:
            return self.send(404, {"error": "not_found"})
        self.send(200, content, kind)

    def do_POST(self):
        if self.path not in ("/api/action", "/api/host"):
            return self.send(404, {"error": "not_found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise Rejected("invalid_command")
            raw = self.rfile.read(length)
            command = json.loads(raw)
            connection = database(self.server.db)
            try:
                # IMMEDIATE serializes read/modify/write commands.  Since the
                # candidate is fully validated before UPDATE, concurrent
                # disjoint requests cannot overwrite one another.
                connection.execute("BEGIN IMMEDIATE")
                before = load(connection)
                operation = apply if self.path == "/api/action" else host
                after = operation(before, command)
                connection.execute(
                    "UPDATE workspace SET payload=? WHERE id=1",
                    (json.dumps(after, ensure_ascii=False),),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()
            return self.send(
                200,
                after["state"]
                if self.path == "/api/action"
                else {"nodes": after["document"], "current": after["current"]},
            )
        except (ValueError, TypeError, KeyError, UnicodeError, sqlite3.Error) as error:
            # Rejected carries exactly the public domain error code.  Other
            # malformed JSON/transport/database values are deliberately
            # normalized instead of exposing implementation details.
            code = str(error) if isinstance(error, Rejected) else "invalid_command"
            return self.send(400, {"error": code})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default="workspace.sqlite")
    args = parser.parse_args()
    connection = database(args.db)
    connection.close()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.db = args.db
    print(json.dumps({"port": server.server_port}), flush=True)
    server.serve_forever()

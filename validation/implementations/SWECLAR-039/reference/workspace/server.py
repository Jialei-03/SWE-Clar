"""Local HTTP dashboard with SQLite workflow persistence and a prepared peer."""
import argparse
import json
import select
import signal
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from controller import WorkflowError, command, discovery, lifecycle


EMPTY = {"devices": [], "paired": [], "connected": None, "commands": [], "telemetry": []}


def read(connection):
    row = connection.execute("SELECT document FROM state WHERE id=1").fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO state (id, document) VALUES (1, ?)",
            (json.dumps(EMPTY, ensure_ascii=False, allow_nan=False),),
        )
        return dict(EMPTY)
    return json.loads(row[0])


def write(connection, state):
    connection.execute(
        "UPDATE state SET document=? WHERE id=1",
        (json.dumps(state, ensure_ascii=False, allow_nan=False),),
    )


def _reject_constant(value):
    raise ValueError("Nonfinite JSON number")


class Handler(BaseHTTPRequestHandler):
    # The application owns the workflow lock, not the HTTP server's socket
    # accept loop.  Separate requests can therefore be handled concurrently,
    # while all state reads/peer exchanges remain serialized.
    server_version = "FramedDeviceMonitor/1"

    def log_message(self, *_):
        pass

    def send(self, data, status=200, kind="application/json"):
        if kind == "application/json":
            payload = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        else:
            payload = data.encode("utf-8") if isinstance(data, str) else data
        self.send_response(status)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/":
            try:
                html = (Path(__file__).with_name("index.html")).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                return self.send({"error": "server_failure"}, 500)
            return self.send(html, kind="text/html")

        if self.path == "/api/state":
            with self.server.lock:
                with sqlite3.connect(self.server.database) as connection:
                    return self.send(read(connection))

        return self.send({"error": "not_found"}, 404)

    def _json_body(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            raise ValueError("Invalid content length")
        if not 1 <= size <= 65536:
            raise ValueError("Body size")
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise ValueError("Truncated request body")
        body = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
        if not isinstance(body, dict):
            raise ValueError("Expected object")
        # Also reject exponent overflow in ordinary JSON numbers (the parser
        # represents those as infinity even when no NaN/Infinity token was
        # present in the request text).
        json.dumps(body, allow_nan=False)
        return body

    def do_POST(self):
        operations = {"/api/scan", "/api/pair", "/api/connect", "/api/disconnect", "/api/command"}
        if self.path not in operations:
            return self.send({"error": "not_found"}, 404)

        try:
            body = self._json_body()
        except (ValueError, UnicodeError, TypeError, RecursionError):
            return self.send({"error": "invalid_request"}, 400)

        operation = self.path.removeprefix("/api/")
        failure = None
        result = None
        with self.server.lock:
            with sqlite3.connect(self.server.database) as connection:
                state = read(connection)
                try:
                    if operation == "scan":
                        state["devices"] = discovery(self.server.peer_port, body.get("service"))
                        # A successful scan only retains a live connection if
                        # its target is still in the newly filtered result.
                        if state["connected"] not in {
                            item["device_id"] for item in state["devices"]
                        }:
                            state["connected"] = None
                        result = state
                    elif operation == "command":
                        result = {"result": command(state, body, self.server.peer_port)}
                    else:
                        lifecycle(state, operation, body, self.server.peer_port)
                        result = state
                except WorkflowError as error:
                    failure = error
                    # A peer transport/protocol failure invalidates the live
                    # connection, but never rolls back durable histories.
                    if error.status == 502:
                        state["connected"] = None

                # Persist even on a 502 so the cleared connection is durable,
                # and on local denials so any earlier valid state is retained.
                write(connection, state)

        if failure is not None:
            return self.send({"error": failure.code}, failure.status)
        return self.send(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default="/tmp/devices.sqlite")
    parser.add_argument("--peer-port", type=int)
    args = parser.parse_args()

    # Exit through the finally block so an automatically launched peer is
    # always terminated with the manager process.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    with sqlite3.connect(args.db) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, document TEXT NOT NULL)")
        connection.execute(
            "INSERT OR IGNORE INTO state VALUES (1, ?)",
            (json.dumps(EMPTY, ensure_ascii=False, allow_nan=False),),
        )
        state = read(connection)
        # Discovery and the live peer connection are session state.  Pairing,
        # command history, and telemetry deliberately survive a restart.
        state["devices"] = []
        state["connected"] = None
        write(connection, state)

    worker = None
    try:
        if args.peer_port is None:
            peer_script = str(Path(__file__).with_name("peer.py"))
            worker = subprocess.Popen(
                [sys.executable, peer_script, "--port", "0", "--state", args.db + ".peer.json"],
                stdout=subprocess.PIPE,
                text=True,
            )
            if worker.stdout is None or not select.select([worker.stdout], [], [], 5)[0]:
                raise RuntimeError("Synthetic peer did not start")
            line = worker.stdout.readline()
            args.peer_port = int(json.loads(line)["port"])

        server = ThreadingHTTPServer((args.host, args.port), Handler)
        server.daemon_threads = True
        server.database = args.db
        server.peer_port = args.peer_port
        server.lock = threading.Lock()
        print(json.dumps({"port": server.server_port}), flush=True)
        server.serve_forever()
    finally:
        if worker is not None:
            worker.terminate()
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)


if __name__ == "__main__":
    main()

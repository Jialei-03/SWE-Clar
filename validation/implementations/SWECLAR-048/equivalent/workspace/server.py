import argparse
import copy
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from control import ControlError, discovery, initial, command
from pixels import png, scale
from wire import SourceError, exchange


ROOT = Path(__file__).resolve().parent



def load(path):
    """Create/read the small persistent settings record."""
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        row = db.execute("SELECT payload FROM settings WHERE id=1").fetchone()
    if row is None:
        return None
    try:
        value = json.loads(row[0])
    except (TypeError, ValueError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None



def save(path, state):
    """Persist exactly the settings allowed to survive a process restart."""
    settings = {key: state[key] for key in ("resolution", "kiosk")}
    with sqlite3.connect(path) as db:
        db.execute("INSERT OR REPLACE INTO settings VALUES(1, ?)", (json.dumps(settings),))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, status, body, kind="application/json", headers=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            raise ControlError("invalid_event")
        if not 0 < length <= 4096:
            raise ControlError("invalid_event")
        try:
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError, RecursionError):
            raise ControlError("invalid_event")

    def do_GET(self):
        if self.path == "/api/state":
            with self.server.lock:
                state = copy.deepcopy(self.server.state)
            self.send(200, state)
            return

        if self.path == "/api/frame":
            try:
                with self.server.lock:
                    state = copy.deepcopy(self.server.state)
                request = {"op": "frame", "input": state["display_input"]}
                if state["display_input"] == "preview":
                    if state["selected"] is None:
                        raise ControlError("no_device")
                    request["device_id"] = state["selected"]
                sequence, width, height, rgb = exchange(self.server.camera_port, request)
                output_width, output_height = map(int, state["resolution"].split("x"))
                transformed = scale(rgb, width, height, output_width, output_height, state["zoom"])
                self.send(
                    200,
                    png(transformed, output_width, output_height),
                    "image/png",
                    {
                        "X-Frame-Sequence": sequence,
                        "X-Display-Input": state["display_input"],
                    },
                )
            except ControlError as error:
                self.send(409, {"error": str(error)})
            except SourceError as error:
                self.send(502, {"error": str(error)})
            return

        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/viewer.js": ("viewer.js", "text/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
        }
        if self.path not in files:
            self.send(404, {"error": "not_found"})
            return
        name, kind = files[self.path]
        self.send(200, (ROOT / name).read_bytes(), kind)

    def do_POST(self):
        if self.path not in ("/api/scan", "/api/control"):
            self.send(404, {"error": "not_found"})
            return

        try:
            event = self._json_body()
        except ControlError as error:
            self.send(400, {"error": str(error)})
            return

        if self.path == "/api/scan":
            if event != {}:
                self.send(400, {"error": "invalid_event"})
                return
            try:
                # Do not hold the application lock during network I/O.  The
                # current state is read again below so a concurrent control
                # cannot be lost when the catalog arrives.
                devices = exchange(self.server.camera_port, {"op": "list"})
            except SourceError as error:
                self.send(502, {"error": str(error)})
                return
            try:
                with self.server.lock:
                    after = discovery(self.server.state, devices)
                    save(self.server.db, after)
                    self.server.state = after
            except (OSError, sqlite3.Error) as error:
                self.send(500, {"error": "storage_error"})
                return
            self.send(200, after)
            return

        try:
            with self.server.lock:
                after = command(self.server.state, event)
                save(self.server.db, after)
                self.server.state = after
        except ControlError as error:
            self.send(400, {"error": str(error)})
            return
        except (OSError, sqlite3.Error):
            self.send(500, {"error": "storage_error"})
            return
        self.send(200, after)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default="camera.sqlite")
    parser.add_argument("--camera-port", type=int)
    args = parser.parse_args()

    source = None
    if args.camera_port is None:
        from synthetic_source import Source

        source = Source()
        args.camera_port = source.start()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.db = args.db
    server.camera_port = args.camera_port
    server.lock = threading.RLock()
    server.state = initial(load(args.db))
    try:
        server.state = discovery(server.state, exchange(args.camera_port, {"op": "list"}))
    except SourceError:
        # A failed initial discovery leaves the fresh/persisted settings
        # usable; an explicit scan can recover later.
        pass

    print(json.dumps({"port": server.server_port}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if source:
            source.stop()

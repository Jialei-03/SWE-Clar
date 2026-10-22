"""Actual local HTTP hiring application; no production services or original assets."""
import argparse
import hmac
import json
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from common import Problem, fields, ident, require
from storage import connect, initialize, password_hash, public_user
import marketplace


def _object_without_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        # The prepared harness expects ordinary application output to remain
        # machine-readable; HTTP access logs are not useful here.
        pass

    def send(self, status, payload, kind="application/json", filename=None):
        if kind == "application/json":
            data = json.dumps(
                payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
        else:
            data = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        if filename is not None:
            # Filenames reaching this method are either fixed names or the
            # strictly validated ASCII resume basename.
            self.send_header("Content-Disposition", 'attachment; filename="' + filename + '"')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def do_PUT(self):
        self.handle_request()

    def handle_request(self):
        try:
            route = urlparse(self.path)
            path = route.path
            query_values = parse_qs(route.query, keep_blank_values=True)
            require(all(len(values) == 1 for values in query_values.values()))
            query = {key: values[0] for key, values in query_values.items()}

            static = {
                "/": ("index.html", "text/html"),
                "/ui.js": ("ui.js", "text/javascript"),
                "/style.css": ("style.css", "text/css"),
            }
            if self.command == "GET" and path in static:
                name, kind = static[path]
                self.send(200, (Path(__file__).parent / "web" / name).read_bytes(), kind)
                return
            if self.command == "GET" and path == "/health":
                fields(query, [])
                self.send(200, {"ok": True})
                return

            body = {}
            if self.command in ("POST", "PUT"):
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                except (TypeError, ValueError):
                    raise Problem(400, "invalid")
                require(0 < size <= 400000)
                raw = self.rfile.read(size)
                # parse_constant turns NaN/Infinity into a value which then
                # fails the endpoint's ordinary type validation.
                body = json.loads(
                    raw.decode("utf-8"),
                    parse_constant=lambda _: None,
                    object_pairs_hook=_object_without_duplicate_keys,
                )
                require(isinstance(body, dict))

            with connect(self.server.db) as db:
                # A write lock for every request makes the multi-step workflow
                # decisions (including conflict checks) one SQLite transaction.
                db.execute("BEGIN IMMEDIATE")
                result = self.dispatch(db, path, query, body)

            if isinstance(result, tuple):
                data, kind, filename = result
                self.send(200, data, kind, filename)
            else:
                self.send(200, result)
        except Problem as error:
            self.send(error.status, {"error": {"code": error.code}})
        except (json.JSONDecodeError, UnicodeError, ValueError, TypeError):
            self.send(400, {"error": {"code": "invalid"}})
        except sqlite3.IntegrityError:
            # All expected uniqueness races are conflicts.  The transaction
            # context has rolled the failed statement back before this branch.
            self.send(409, {"error": {"code": "conflict"}})
        except sqlite3.Error:
            self.send(503, {"error": {"code": "storage_unavailable"}})

    def dispatch(self, db, path, query, body):
        method = self.command
        if method == "POST" and path == "/api/login":
            fields(query, [])
            fields(body, ["id", "password"])
            require(ident(body["id"]) and isinstance(body["password"], str))
            row = db.execute("SELECT * FROM users WHERE id=?", (body["id"],)).fetchone()
            valid = False
            if row is not None:
                try:
                    salt = row["password_hash"].split("$", 1)[0]
                    valid = hmac.compare_digest(
                        row["password_hash"], password_hash(body["password"], salt)
                    )
                except (AttributeError, TypeError, ValueError):
                    valid = False
            require(valid, "unauthorized", 401)
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO sessions(token,user_id) VALUES(?,?)", (token, row["id"]))
            return {"token": token, "user": public_user(row)}

        token_header = self.headers.get("Authorization", "")
        require(token_header.startswith("Bearer "), "unauthorized", 401)
        token = token_header[7:]
        require(token != "", "unauthorized", 401)
        user = db.execute(
            """SELECT users.* FROM users
               JOIN sessions ON sessions.user_id=users.id
               WHERE sessions.token=?""",
            (token,),
        ).fetchone()
        require(user is not None, "unauthorized", 401)

        if method in ("POST", "PUT"):
            fields(query, [])
        if method == "POST" and path == "/api/logout":
            fields(body, [])
            # Only the bearer token used for this request is revoked.
            db.execute("DELETE FROM sessions WHERE token=?", (token,))
            return {"ok": True}
        if method == "GET" and path == "/api/me":
            fields(query, [])
            clock_row = db.execute("SELECT value FROM meta WHERE key='clock_ms'").fetchone()
            require(clock_row is not None, "storage_unavailable", 503)
            try:
                clock_ms = json.loads(clock_row["value"])
            except (TypeError, ValueError, json.JSONDecodeError):
                raise Problem(503, "storage_unavailable")
            return {"user": public_user(user), "clock_ms": clock_ms}
        return marketplace.dispatch(db, user, method, path, query, body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, default=Path("fixtures/demo.json"))
    args = parser.parse_args()
    initialize(args.db, args.fixtures)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    server.db = args.db
    print(json.dumps({"port": server.server_port}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

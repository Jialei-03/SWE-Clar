"""Loopback HTTP/SQLite adapter for the lesson workflow."""

import copy
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from solution import process_music_action
from studio_client import StudioClient


DB = os.environ["STUDIO_DB"]
CONFIG = json.loads(Path(os.environ["STUDIO_CONFIG"]).read_text())
SERVICE = StudioClient(CONFIG["provider_url"], CONFIG.get("provider_token"))


# Runtime/configuration values must not become part of the workflow snapshot.
# The normal configuration already keeps them outside initial_state; removing
# these names also protects against an accidentally over-inclusive fixture.
_RUNTIME_KEYS = {"sessions", "provider_url", "provider_token"}


def _workflow_initial_state():
    value = copy.deepcopy(CONFIG.get("initial_state", {}))
    if not isinstance(value, dict):
        return {}
    for key in _RUNTIME_KEYS | {"result", "error"}:
        value.pop(key, None)
    return value


def _persistable_state(value):
    state = copy.deepcopy(value)
    if isinstance(state, dict):
        for key in _RUNTIME_KEYS | {"result", "error"}:
            state.pop(key, None)
    return state


with sqlite3.connect(DB, timeout=30) as db:
    db.execute(
        "CREATE TABLE IF NOT EXISTS studio "
        "(id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL)"
    )
    db.execute(
        "INSERT OR IGNORE INTO studio(id,state) VALUES(1,?)",
        (json.dumps(_workflow_initial_state(), separators=(",", ":")),),
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        # Authorization headers and provider URLs should never be written to
        # the process log by this local component.
        return

    def reply(self, status, body):
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    @staticmethod
    def _authenticated_user(authorization):
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            return None
        token = authorization[len("Bearer ") :]
        if not token or not isinstance(CONFIG.get("sessions"), dict):
            return None
        try:
            user = CONFIG["sessions"].get(token)
        except (TypeError, ValueError):
            return None
        # Session values are user identifiers, not user objects.  Keeping this
        # check strict avoids treating arbitrary config data as a session.
        return user if isinstance(user, (str, int)) and not isinstance(user, bool) else None

    def _read_action(self):
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else 0
        except (TypeError, ValueError):
            raise ValueError("invalid request")
        if length < 0:
            raise ValueError("invalid request")
        raw = self.rfile.read(length)
        action = json.loads(raw.decode("utf-8"))
        if not isinstance(action, dict):
            raise ValueError("invalid request")
        return action

    def do_POST(self):
        if self.path != "/actions":
            self.reply(404, {"error": {"code": "not_found"}})
            return

        user_id = self._authenticated_user(self.headers.get("Authorization"))
        if user_id is None:
            # Consume a declared body so a client which reuses the connection
            # cannot have the rejected request's bytes parsed as a new
            # request.  Nothing from it is interpreted or returned.
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 0:
                    self.rfile.read(length)
            except (TypeError, ValueError):
                pass
            self.reply(401, {"error": {"code": "unauthenticated"}})
            return

        try:
            action = self._read_action()
        except Exception:
            self.reply(400, {"error": {"code": "invalid_request"}})
            return

        # The authenticated session, rather than caller-supplied fields, owns
        # both actor and viewer identity.
        action["actor_id"] = user_id
        action["viewer_id"] = user_id

        connection = None
        response_status = 500
        response_body = {"error": {"code": "internal_error"}}
        transaction_open = False
        try:
            # BEGIN IMMEDIATE serializes the complete read/check/provider/
            # commit sequence.  Thus two requests cannot both observe an open
            # slot or spend the same event before either commits.
            connection = sqlite3.connect(DB, timeout=30)
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("BEGIN IMMEDIATE")
            transaction_open = True
            row = connection.execute(
                "SELECT state FROM studio WHERE id=1"
            ).fetchone()
            if row is None:
                raise RuntimeError("missing state")
            state = json.loads(row[0])
            if not isinstance(state, dict):
                raise RuntimeError("invalid stored state")

            # A config token pointing at a user not present in the private
            # state is not a valid session.  The response remains a bare auth
            # error and does not reveal the state contents.
            users = state.get("users")
            try:
                known_user = isinstance(users, dict) and user_id in users
            except TypeError:
                known_user = False
            if not known_user:
                connection.rollback()
                transaction_open = False
                response_status = 401
                response_body = {"error": {"code": "unauthenticated"}}
            else:
                try:
                    next_state = process_music_action(state, action, SERVICE)
                except Exception:
                    # Business/provider failures are normally converted by the
                    # workflow.  This fallback still never returns exception
                    # text or a private state snapshot.
                    next_state = {"error": {"code": "invalid_request"}}
                if not isinstance(next_state, dict) or "error" in next_state:
                    error = (
                        next_state.get("error")
                        if isinstance(next_state, dict)
                        else None
                    )
                    if not isinstance(error, dict):
                        error = {"code": "invalid_request"}
                    connection.rollback()
                    transaction_open = False
                    response_status = 400
                    response_body = {"error": error}
                else:
                    result = next_state.get("result", {})
                    stored = _persistable_state(next_state)
                    connection.execute(
                        "UPDATE studio SET state=? WHERE id=1",
                        (json.dumps(stored, separators=(",", ":")),),
                    )
                    connection.commit()
                    transaction_open = False
                    response_status = 200
                    # Only this scoped result crosses the HTTP boundary.
                    response_body = {
                        "result": result if isinstance(result, dict) else {}
                    }
        except sqlite3.OperationalError:
            if connection is not None and transaction_open:
                connection.rollback()
                transaction_open = False
            response_status = 503
            response_body = {"error": {"code": "storage_unavailable"}}
        except Exception:
            if connection is not None and transaction_open:
                connection.rollback()
                transaction_open = False
            response_status = 500
            response_body = {"error": {"code": "internal_error"}}
        finally:
            if connection is not None:
                if transaction_open:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                connection.close()

        self.reply(response_status, response_body)


class Server(ThreadingHTTPServer):
    request_queue_size = 32


if __name__ == "__main__":
    server = Server(("127.0.0.1", int(os.environ.get("PORT", 0))), Handler)
    print(json.dumps({"port": server.server_port}), flush=True)
    server.serve_forever()

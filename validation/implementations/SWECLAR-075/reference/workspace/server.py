"""Small loopback HTTP service for the local attendance fixture."""

from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import json
import os
from typing import Any

from store import Error, Store


ROOT = Path(__file__).resolve().parent
config = json.loads(Path(os.environ["CHECKIN_CONFIG"]).read_text())
clock_path = os.environ.get("CHECKIN_CLOCK_FILE")
clock = (lambda: float(Path(clock_path).read_text())) if clock_path else None
store = Store(os.environ["CHECKIN_DATABASE"], config, clock)


class Handler(BaseHTTPRequestHandler):
    """Translate HTTP requests into store operations without trusting callers."""

    def log_message(self, *_args: Any) -> None:
        # The fixture is normally launched with its port on stdout; avoid
        # mixing request logs into that machine-readable startup line.
        return

    def token(self) -> str:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return ""
        morsel = cookie.get("session")
        return morsel.value if morsel is not None else ""

    def send(self, status: int, data: Any, headers: dict[str, str] | None = None) -> None:
        is_bytes = isinstance(data, bytes)
        if is_bytes:
            raw = data
            content_type = "text/plain; charset=utf-8"
        else:
            raw = json.dumps(data, allow_nan=False, separators=(",", ":")).encode(
                "utf-8"
            )
            content_type = "application/json; charset=utf-8"
        supplied = dict(headers or {})
        supplied.setdefault("Content-Type", content_type)
        self.send_response(status)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in supplied.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self) -> Any:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            raise Error("invalid_request") from None
        if length < 0 or length > 1_048_576:
            raise Error("invalid_request")
        try:
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise Error("invalid_request") from None

    @staticmethod
    def public_sites() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        sites = config.get("sites", [])
        if not isinstance(sites, list):
            raise Error("invalid_site", 500)
        # Keep the configured site contract, but never serialize arbitrary
        # top-level/private configuration fields.
        allowed = ("id", "name", "latitude", "longitude", "radius_m", "active")
        for site in sites:
            if not isinstance(site, dict) or not site.get("active"):
                continue
            result.append({key: site[key] for key in allowed if key in site})
        return result

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path = urlsplit(self.path).path
        try:
            if path in ("/", "/app.js", "/style.css"):
                filename = "index.html" if path == "/" else path[1:]
                content_types = {
                    "/": "text/html; charset=utf-8",
                    "/app.js": "text/javascript; charset=utf-8",
                    "/style.css": "text/css; charset=utf-8",
                }
                try:
                    content = (ROOT / filename).read_bytes()
                except OSError:
                    raise Error("not_found", 404) from None
                return self.send(
                    200, content, {"Content-Type": content_types[path]}
                )

            if path == "/me":
                return self.send(200, store.actor(self.token()))
            if path == "/sites":
                store.actor(self.token())
                return self.send(200, self.public_sites())
            if path == "/navigation":
                store.actor(self.token())
                sections = config.get("sections", [])
                if not isinstance(sections, list):
                    raise Error("invalid_navigation", 500)
                return self.send(
                    200, {"sections": list(sections), "primary": "Plans"}
                )
            if path == "/history":
                actor = store.actor(self.token())
                return self.send(200, store.history(actor["id"]))
            raise Error("not_found", 404)
        except Error as error:
            self.send(error.status, {"error": error.code})
        except (TypeError, OverflowError, ValueError):
            self.send(400, {"error": "invalid_request"})
        except Exception:
            # Do not put tracebacks, database fields, or configuration into a
            # public response.
            self.send(500, {"error": "server_error"})

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        try:
            action = self.read_json()
            if not isinstance(action, dict):
                raise Error("invalid_request")
            path = urlsplit(self.path).path

            if path == "/register":
                return self.send(200, store.register(action))
            if path == "/login":
                token = store.login(action)
                actor = store.actor(token)
                return self.send(
                    200,
                    actor,
                    {
                        "Set-Cookie": (
                            f"session={token}; Path=/; HttpOnly; SameSite=Strict"
                        )
                    },
                )

            actor = store.actor(self.token())
            if path == "/checkin":
                return self.send(200, store.checkin(actor["id"], action))
            if path == "/checkout":
                return self.send(200, store.checkout(actor["id"]))
            if path == "/logout":
                result = store.logout(self.token())
                return self.send(
                    200,
                    result,
                    {
                        "Set-Cookie": (
                            "session=; Max-Age=0; Path=/; HttpOnly; "
                            "SameSite=Strict"
                        )
                    },
                )
            raise Error("not_found", 404)
        except Error as error:
            self.send(error.status, {"error": error.code})
        except (TypeError, OverflowError, ValueError):
            self.send(400, {"error": "invalid_request"})
        except Exception:
            self.send(500, {"error": "server_error"})


server = ThreadingHTTPServer(
    ("127.0.0.1", int(os.environ.get("PORT", "0"))), Handler
)
print(json.dumps({"port": server.server_port}), flush=True)
server.serve_forever()

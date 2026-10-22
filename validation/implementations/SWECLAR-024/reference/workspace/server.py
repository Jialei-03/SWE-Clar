"""HTTP entry point for the direct event video service."""

from __future__ import annotations

import json
import os
import re
import signal
from datetime import datetime, timezone
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from store import NotFoundError, Store


ROOT = Path(__file__).resolve().parent
with Path(os.environ["STREAM_CONFIG"]).open(encoding="utf-8") as config_file:
    config = json.load(config_file)
store = Store(os.environ["STREAM_DATABASE"], config)


class RequestError(ValueError):
    pass


class Handler(BaseHTTPRequestHandler):
    # Runtime media credentials and administration credentials are never logged.
    def log_message(self, *_args: Any) -> None:
        return

    def _session(self) -> tuple[str, str, bool]:
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except (ValueError, CookieError):  # pragma: no cover - parser variation
            cookies = SimpleCookie()
        token = cookies["session"].value if "session" in cookies else None
        return store.session(token)

    @staticmethod
    def _cookie(token: str) -> str:
        return f"session={token}; HttpOnly; SameSite=Strict; Path=/"

    def _send(
        self,
        status: int,
        data: bytes | dict[str, Any] | list[Any],
        mime: str = "application/json",
        headers: dict[str, str] | None = None,
        head_only: bool = False,
    ) -> None:
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if not head_only:
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _error(self, status: int, code: str, head_only: bool = False) -> None:
        self._send(status, {"error": code}, headers={"Cache-Control": "no-store"}, head_only=head_only)

    def _path(self) -> str:
        return urlsplit(self.path).path

    def _parse_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise RequestError("invalid_body") from exc
        if length <= 0 or length > 20000:
            raise RequestError("invalid_body")
        try:
            raw = self.rfile.read(length)
            body = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequestError("invalid_body") from exc
        if not isinstance(body, dict):
            raise RequestError("invalid_body")
        return body

    def _admin(self) -> None:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise PermissionError("admin_required")
        # Store performs constant-time comparison against the protected config
        # token.  No body field can act as an administrative credential.
        store.admin(header[7:])

    def _static(self, filename: str, mime: str, head_only: bool) -> None:
        viewer, token, new = self._session()
        del viewer
        data = (ROOT / filename).read_bytes()
        headers = {"Cache-Control": "no-store"}
        if new:
            headers["Set-Cookie"] = self._cookie(token)
        self._send(200, data, mime, headers, head_only=head_only)

    def _media_response(self, ident: str, head_only: bool) -> None:
        path = store.media_path(ident)
        if path is None:
            self._error(404, "not_found", head_only)
            return
        size = path.stat().st_size
        if size <= 0:
            self._error(404, "not_found", head_only)
            return
        range_header = self.headers.get("Range")
        start = 0
        end = size - 1
        status = 200
        headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-store"}
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match or (not match.group(1) and not match.group(2)) or "," in range_header:
                self._send(
                    416,
                    b"",
                    "video/mp4",
                    {"Accept-Ranges": "bytes", "Content-Range": f"bytes */{size}"},
                    head_only,
                )
                return
            try:
                if match.group(1):
                    start = int(match.group(1))
                    end = int(match.group(2)) if match.group(2) else size - 1
                else:
                    suffix = int(match.group(2))
                    if suffix <= 0:
                        raise ValueError
                    start = max(0, size - suffix)
                    end = size - 1
            except ValueError:
                self._send(
                    416,
                    b"",
                    "video/mp4",
                    {"Accept-Ranges": "bytes", "Content-Range": f"bytes */{size}"},
                    head_only,
                )
                return
            if start >= size or start > end:
                self._send(
                    416,
                    b"",
                    "video/mp4",
                    {"Accept-Ranges": "bytes", "Content-Range": f"bytes */{size}"},
                    head_only,
                )
                return
            end = min(end, size - 1)
            status = 206
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"

        length = end - start + 1
        headers["Content-Length"] = str(length)
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        # _send normally emits Content-Length; the media path is streamed to
        # avoid loading a recording into memory for every browser range read.
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if head_only:
            return
        try:
            with path.open("rb") as source:
                source.seek(start)
                remaining = length
                while remaining:
                    block = source.read(min(1024 * 1024, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _get(self, head_only: bool = False) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        params = parse_qs(parsed.query, keep_blank_values=True)
        if path == "/":
            return self._static("index.html", "text/html; charset=utf-8", head_only)
        if path == "/app.js":
            return self._static("app.js", "text/javascript; charset=utf-8", head_only)
        if path == "/style.css":
            return self._static("style.css", "text/css; charset=utf-8", head_only)
        if path == "/calendar":
            now = params.get("now", [datetime.now(timezone.utc).isoformat()])[0]
            return self._send(200, store.calendar(now), head_only=head_only)
        if path == "/archives":
            query = params.get("q", [""])[0]
            start = params.get("start", [None])[0] or None
            end = params.get("end", [None])[0] or None
            return self._send(200, store.search(query, start, end), head_only=head_only)
        if path.startswith("/media/"):
            encoded = path[len("/media/") :]
            if not encoded or "/" in encoded:
                return self._error(404, "not_found", head_only)
            try:
                ident = unquote(encoded)
            except Exception:
                return self._error(404, "not_found", head_only)
            return self._media_response(ident, head_only)
        self._error(404, "not_found", head_only)

    def do_GET(self) -> None:
        try:
            self._get(False)
        except NotFoundError:
            self._error(404, "not_found")
        except (ValueError, KeyError, TypeError):
            self._error(400, "request_failed")
        except (OSError, json.JSONDecodeError):
            self._error(400, "request_failed")
        except Exception:
            self._error(400, "request_failed")

    def do_HEAD(self) -> None:
        try:
            self._get(True)
        except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError):
            self._error(400, "request_failed", True)
        except Exception:
            self._error(400, "request_failed", True)

    def do_POST(self) -> None:
        path = self._path()
        methods = {
            "/event": store.create,
            "/cancel": store.cancel,
            "/start": store.start,
            "/end": store.end,
            "/publish": store.publish,
        }
        if path != "/view" and path not in methods:
            self._error(404, "not_found")
            return
        try:
            # Authenticate management requests before parsing their body.  A
            # caller without the admin credential cannot probe validation
            # behavior through malformed management payloads.
            if path != "/view":
                self._admin()
            body = self._parse_body()
            if path == "/view":
                viewer, session, new = self._session()
                result = store.view(body, viewer, session)
                headers = {"Cache-Control": "no-store"}
                if new:
                    headers["Set-Cookie"] = self._cookie(session)
                self._send(200, result, headers=headers)
                return
            self._send(200, methods[path](body), headers={"Cache-Control": "no-store"})
        except PermissionError:
            self._error(403, "denied")
        except NotFoundError:
            self._error(404, "not_found")
        except (RequestError, ValueError, KeyError, TypeError, OSError, json.JSONDecodeError):
            self._error(400, "request_failed")
        except Exception:
            self._error(400, "request_failed")


server = ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "0"))), Handler)
server.daemon_threads = True


def stop(*_args: Any) -> None:
    raise SystemExit(0)


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
print(json.dumps({"port": server.server_port}), flush=True)
try:
    server.serve_forever()
finally:
    store.close()
    server.server_close()

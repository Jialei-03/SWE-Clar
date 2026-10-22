"""Durable event, archive, and anonymous-view state."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from media import Media


class NotFoundError(LookupError):
    pass


def instant(value: Any) -> str:
    """Parse an explicit-timezone ISO-8601 value and normalize it to UTC."""

    if not isinstance(value, str) or not value:
        raise ValueError("timezone_required")
    try:
        # datetime.fromisoformat accepts a literal Z on current supported
        # Python versions, but replacing it also keeps this compatible with
        # older Python releases.
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone_required")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _event_id(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError("invalid_event")
    # IDs are configured host values, but must not be usable as path
    # components.  Other punctuation and Unicode remain valid configured IDs.
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError("invalid_event")
    return value


class Store:
    def __init__(self, path: str, config: dict[str, Any]):
        self.path = str(path)
        database_parent = Path(self.path).expanduser().parent
        database_parent.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.media = Media(config["media_root"])
        self.lock = threading.RLock()
        with self.db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS events(
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    start TEXT NOT NULL,
                    end TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS archives(
                    event TEXT PRIMARY KEY REFERENCES events(id),
                    payload TEXT NOT NULL,
                    published INTEGER NOT NULL DEFAULT 0,
                    terms TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS views(
                    event TEXT REFERENCES archives(event),
                    viewer TEXT NOT NULL,
                    session TEXT NOT NULL,
                    PRIMARY KEY(event,viewer,session)
                );
                CREATE TABLE IF NOT EXISTS sessions(
                    token TEXT PRIMARY KEY,
                    viewer TEXT NOT NULL
                );
                """
            )
            # A process restart cannot safely continue a child MediaMTX that
            # it no longer owns.  It is not an ended recording evidence.
            db.execute("UPDATE events SET status='interrupted' WHERE status='live'")

    def db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def close(self) -> None:
        with self.lock:
            self.media.close()
            with self.db() as db:
                db.execute("UPDATE events SET status='interrupted' WHERE status='live'")

    def admin(self, token: Any) -> None:
        expected = self.config.get("admin_token")
        if (
            not isinstance(token, str)
            or not isinstance(expected, str)
            or not expected
            or not hmac.compare_digest(token, expected)
        ):
            raise PermissionError("admin_required")

    def _configured_key(self, event: str) -> str:
        keys = self.config.get("stream_keys")
        if not isinstance(keys, dict) or event not in keys or not isinstance(keys[event], str) or not keys[event]:
            raise ValueError("unconfigured_event")
        return keys[event]

    def create(self, body: dict[str, Any]) -> dict[str, str]:
        if not isinstance(body, dict):
            raise ValueError("invalid_event")
        # Parse and validate everything before opening the transaction.  A bad
        # edit therefore cannot leave a partially-created row.
        ident = _event_id(body.get("event_id"))
        title = body.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("invalid_event")
        title = title.strip()
        start = instant(body.get("start"))
        end = instant(body.get("end"))
        if end <= start:
            raise ValueError("invalid_event")
        self._configured_key(ident)
        with self.lock, self.db() as db:
            try:
                db.execute(
                    "INSERT INTO events(id,title,start,end,status) VALUES (?,?,?,?,?)",
                    (ident, title, start, end, "scheduled"),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("event_exists") from exc
        return {"event_id": ident}

    def calendar(self, now: Any) -> list[dict[str, str]]:
        normalized = instant(now)
        with self.db() as db:
            rows = db.execute(
                """
                SELECT id,title,start,end FROM events
                WHERE status='scheduled' AND start>=?
                ORDER BY start ASC,id ASC
                """,
                (normalized,),
            ).fetchall()
        return [
            {"event_id": row[0], "title": row[1], "start": row[2], "end": row[3]}
            for row in rows
        ]

    def cancel(self, body: dict[str, Any]) -> dict[str, bool]:
        if not isinstance(body, dict):
            raise ValueError("invalid_event")
        ident = _event_id(body.get("event_id"))
        with self.lock, self.db() as db:
            row = db.execute("SELECT status FROM events WHERE id=?", (ident,)).fetchone()
            if not row or row[0] != "scheduled":
                raise ValueError("not_scheduled")
            db.execute("UPDATE events SET status='cancelled' WHERE id=?", (ident,))
        return {"cancelled": True}

    def start(self, body: dict[str, Any]) -> dict[str, str]:
        if not isinstance(body, dict):
            raise ValueError("start_denied")
        ident = _event_id(body.get("event_id"))
        supplied = body.get("stream_key")
        expected = self._configured_key(ident)
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied, expected):
            raise ValueError("start_denied")
        with self.lock:
            with self.db() as db:
                row = db.execute("SELECT status FROM events WHERE id=?", (ident,)).fetchone()
                if not row or row[0] != "scheduled":
                    raise ValueError("start_denied")
                try:
                    result = self.media.begin(ident, expected)
                except Exception as exc:
                    # A failed child/configuration start leaves the event
                    # scheduled and does not retain a live media process.
                    self.media.abort(ident)
                    raise ValueError("stream_start_failed") from exc
                try:
                    db.execute("UPDATE events SET status='live' WHERE id=?", (ident,))
                except Exception:
                    self.media.abort(ident)
                    raise
                return result

    def end(self, body: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise ValueError("not_live")
        ident = _event_id(body.get("event_id"))
        with self.lock:
            with self.db() as db:
                row = db.execute("SELECT status FROM events WHERE id=?", (ident,)).fetchone()
                if not row or row[0] != "live":
                    raise ValueError("not_live")
                try:
                    info = self.media.end(ident)
                except Exception as exc:
                    db.execute("UPDATE events SET status='interrupted' WHERE id=?", (ident,))
                    # The surrounding connection context would otherwise
                    # roll this transition back when the public error is
                    # raised.
                    db.commit()
                    raise ValueError("recording_failed") from exc
                try:
                    db.execute(
                        "INSERT INTO archives(event,payload,published,terms) VALUES (?,?,0,?)",
                        (ident, json.dumps(info, separators=(",", ":"), sort_keys=True), "[]"),
                    )
                    db.execute("UPDATE events SET status='ended' WHERE id=?", (ident,))
                except Exception:
                    # The archive is not made public without its durable DB
                    # record; leave the event non-publishable if persistence
                    # itself fails.
                    db.execute("UPDATE events SET status='interrupted' WHERE id=?", (ident,))
                    db.commit()
                    raise ValueError("archive_save_failed")
        return {key: info[key] for key in ("bytes", "sha256", "duration", "frames")}

    @staticmethod
    def _terms(value: Any) -> list[str]:
        if isinstance(value, str):
            # A string is accepted as a compact form; whitespace-separated
            # words are independently searchable while the original phrase is
            # still represented by the same inclusive search behavior.
            values = value.split()
        elif isinstance(value, list):
            values = value
        else:
            raise ValueError("invalid_terms")
        if not values:
            raise ValueError("invalid_terms")
        result: list[str] = []
        seen: set[str] = set()
        for term in values:
            if not isinstance(term, str):
                raise ValueError("invalid_terms")
            clean = term.strip()
            if not clean:
                raise ValueError("invalid_terms")
            folded = clean.casefold()
            if folded not in seen:
                seen.add(folded)
                result.append(clean)
        if not result:
            raise ValueError("invalid_terms")
        return result

    def _rooted_file(self, value: Any) -> Path | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            root = self.media.root.resolve()
            candidate = Path(value)
            if candidate.is_symlink():
                return None
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(root)
        except (OSError, ValueError):
            return None
        if resolved.is_symlink() or not resolved.is_file():
            return None
        return resolved

    @staticmethod
    def _digest(path: Path) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                size += len(block)
                digest.update(block)
        return size, digest.hexdigest()

    def _verified_payload(self, payload: Any) -> tuple[dict[str, Any], Path] | None:
        if not isinstance(payload, dict):
            return None
        path = self._rooted_file(payload.get("path"))
        if path is None:
            return None
        try:
            expected_bytes = int(payload["bytes"])
            expected_hash = payload["sha256"]
        except (KeyError, TypeError, ValueError):
            return None
        if expected_bytes <= 0 or not isinstance(expected_hash, str):
            return None
        try:
            actual_bytes, actual_hash = self._digest(path)
        except OSError:
            return None
        if actual_bytes != expected_bytes or not hmac.compare_digest(actual_hash, expected_hash):
            return None
        return payload, path

    def _archive_row(self, db: sqlite3.Connection, ident: str) -> tuple[Any, ...] | None:
        return db.execute(
            "SELECT payload,published,terms FROM archives WHERE event=?", (ident,)
        ).fetchone()

    def publish(self, body: dict[str, Any]) -> dict[str, bool]:
        if not isinstance(body, dict):
            raise ValueError("invalid_publish")
        ident = _event_id(body.get("event_id"))
        terms = self._terms(body.get("terms"))
        with self.lock, self.db() as db:
            row = self._archive_row(db, ident)
            if not row:
                raise NotFoundError("archive_missing")
            payload_raw, published, _old_terms = row
            if published:
                raise ValueError("already_published")
            try:
                payload = json.loads(payload_raw)
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("invalid_archive") from exc
            if self._verified_payload(payload) is None:
                raise ValueError("media_missing_or_changed")
            db.execute(
                "UPDATE archives SET published=1,terms=? WHERE event=? AND published=0",
                (json.dumps(terms, ensure_ascii=False, separators=(",", ":")), ident),
            )
        return {"published": True}

    def _public_rows(self, query: str, start: Any, end: Any) -> list[dict[str, Any]]:
        normalized_start = instant(start) if start not in (None, "") else None
        normalized_end = instant(end) if end not in (None, "") else None
        if normalized_start and normalized_end and normalized_end < normalized_start:
            raise ValueError("invalid_date_range")
        query = query.strip() if isinstance(query, str) else ""
        with self.db() as db:
            rows = db.execute(
                """
                SELECT e.id,e.title,e.start,a.payload,a.terms
                FROM events e JOIN archives a ON e.id=a.event
                WHERE a.published=1
                ORDER BY e.start ASC,e.id ASC
                """
            ).fetchall()
        result: list[dict[str, Any]] = []
        folded_query = query.casefold()
        for ident, title, event_start, payload_raw, terms_raw in rows:
            try:
                payload = json.loads(payload_raw)
                terms = json.loads(terms_raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(terms, list) or not all(isinstance(term, str) for term in terms):
                continue
            if self._verified_payload(payload) is None:
                # A damaged/lost archive is not advertised as playable.
                continue
            haystack = (str(title) + " " + " ".join(terms)).casefold()
            if folded_query and folded_query not in haystack:
                continue
            if normalized_start and event_start < normalized_start:
                continue
            if normalized_end and event_start >= normalized_end:
                continue
            try:
                duration = float(payload["duration"])
            except (KeyError, TypeError, ValueError):
                continue
            result.append(
                {
                    "event_id": ident,
                    "title": title,
                    "start": event_start,
                    "media_url": "/media/" + quote(ident, safe=""),
                    "duration": duration,
                }
            )
        return result

    def search(self, query: str = "", start: Any = None, end: Any = None) -> list[dict[str, Any]]:
        return self._public_rows(query, start, end)

    def media_path(self, ident: str) -> Path | None:
        ident = _event_id(ident)
        with self.db() as db:
            row = db.execute(
                "SELECT payload FROM archives WHERE event=? AND published=1", (ident,)
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return None
        checked = self._verified_payload(payload)
        return checked[1] if checked else None

    def session(self, token: Any = None) -> tuple[str, str, bool]:
        with self.lock, self.db() as db:
            if isinstance(token, str) and len(token) <= 128:
                row = db.execute("SELECT viewer FROM sessions WHERE token=?", (token,)).fetchone()
                if row and isinstance(row[0], str):
                    return row[0], token, False
            # Both values are server-issued.  A body field named viewer or
            # session is never consulted by view().
            import secrets

            new_token = secrets.token_hex(32)
            viewer = secrets.token_hex(24)
            db.execute("INSERT INTO sessions(token,viewer) VALUES (?,?)", (new_token, viewer))
            return viewer, new_token, True

    def view(self, body: dict[str, Any], viewer: str, session: str) -> dict[str, int]:
        if not isinstance(body, dict):
            raise ValueError("invalid_view")
        ident = _event_id(body.get("event_id"))
        if not isinstance(viewer, str) or not isinstance(session, str):
            raise ValueError("invalid_view")
        with self.lock, self.db() as db:
            row = db.execute(
                "SELECT payload FROM archives WHERE event=? AND published=1", (ident,)
            ).fetchone()
            if not row:
                raise NotFoundError("archive_missing")
            try:
                payload = json.loads(row[0])
            except (TypeError, json.JSONDecodeError) as exc:
                raise NotFoundError("archive_missing") from exc
            if self._verified_payload(payload) is None:
                raise NotFoundError("archive_missing")
            db.execute(
                "INSERT OR IGNORE INTO views(event,viewer,session) VALUES (?,?,?)",
                (ident, viewer, secrets.token_hex(24)),
            )
            count = db.execute("SELECT COUNT(*) FROM views WHERE event=?", (ident,)).fetchone()[0]
        return {"views": int(count)}

"""Private configuration access and durable local-session storage.

The web process keeps the configuration in memory, but only the small public
projections returned by this module are sent to the browser.  Sessions are
represented by random bearer tokens at the HTTP boundary and by SHA-256
hashes in SQLite.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping


UTC = timezone.utc


def _parse_instant(value: Any) -> datetime:
    """Return an ISO-8601 or aware ``datetime`` value in UTC.

    Fixture timestamps and API timestamps must carry a timezone.  Treating a
    naive value as local time would make sample selection depend on the host,
    so it is deliberately rejected instead.
    """

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        # ``fromisoformat`` accepts ``Z`` on recent Python versions, but
        # normalising it also keeps this code portable to older runtimes.
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid_time") from exc
    else:
        raise ValueError("invalid_time")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone_required")
    return parsed.astimezone(UTC)


# Keep the timestamp helper available to callers while allowing the public
# Store.rewind parameter to use the contract's name, ``instant``.
instant = _parse_instant


def point(row: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy the public geographic fields from a fixture row."""

    if not isinstance(row, Mapping):
        raise ValueError("invalid_point")

    values: dict[str, Any] = {}
    for key, bound in (("latitude", 90), ("longitude", 180)):
        value = row.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not -bound <= value <= bound
        ):
            raise ValueError("invalid_point")
        values[key] = value
    return values


def _token_hash(token: str | None) -> str:
    """Hash an HTTP token without ever putting its value in the database."""

    if not isinstance(token, str):
        token = ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Store:
    """Access the private fixture and the durable local session table."""

    def __init__(self, path: str, config: Mapping[str, Any]):
        self.path = path
        self.config = config
        with self.db() as database:
            database.execute(
                "CREATE TABLE IF NOT EXISTS sessions ("
                "hash TEXT PRIMARY KEY, user TEXT NOT NULL"
                ")"
            )

    def db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def login(self, credentials: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        """Verify the supplied local scrypt record and create a new session.

        A malformed, unknown, or mismatching credential deliberately has the
        same failure shape.  The clear token is returned only to the caller so
        it can become an HttpOnly cookie; SQLite receives only its digest.
        """

        valid = False
        record: Mapping[str, Any] | None = None
        username: Any = None
        password: Any = None
        if isinstance(credentials, Mapping):
            username = credentials.get("username")
            password = credentials.get("password")
            if isinstance(username, str) and isinstance(password, str):
                users = self.config.get("users", {})
                if isinstance(users, Mapping):
                    candidate = users.get(username)
                    if isinstance(candidate, Mapping):
                        record = candidate
                        try:
                            salt = bytes.fromhex(candidate["salt"])
                            expected = bytes.fromhex(candidate["password_hash"])
                            actual = hashlib.scrypt(
                                password.encode("utf-8"),
                                salt=salt,
                                n=16384,
                                r=8,
                                p=1,
                            )
                            valid = hmac.compare_digest(actual, expected)
                        except (KeyError, TypeError, ValueError):
                            # A bad private record must not become a server
                            # traceback or disclose which part was malformed.
                            valid = False

        if not valid or record is None:
            raise PermissionError("invalid_login")

        token = secrets.token_urlsafe(32)
        with self.db() as database:
            database.execute(
                "INSERT INTO sessions(hash, user) VALUES (?, ?)",
                (_token_hash(token), username),
            )
        return token, {"username": username, "name": record["name"]}

    def actor(self, token: str | None) -> dict[str, Any]:
        """Resolve a still-valid session to its public actor projection."""

        if not isinstance(token, str) or not token:
            raise PermissionError("login_required")
        with self.db() as database:
            row = database.execute(
                "SELECT user FROM sessions WHERE hash = ?",
                (_token_hash(token),),
            ).fetchone()

        if not row:
            raise PermissionError("login_required")
        users = self.config.get("users", {})
        record = users.get(row[0]) if isinstance(users, Mapping) else None
        if not isinstance(record, Mapping) or "name" not in record:
            # A session for a removed/private user is not usable.
            raise PermissionError("login_required")
        return {"username": row[0], "name": record["name"]}

    def logout(self, token: str | None) -> None:
        """Revoke the session represented by a cookie, if any."""

        with self.db() as database:
            database.execute(
                "DELETE FROM sessions WHERE hash = ?",
                (_token_hash(token),),
            )

    def locations(self, query: str) -> list[dict[str, Any]]:
        """Return local locations whose names contain ``query`` case-folded."""

        if not isinstance(query, str):
            raise ValueError("invalid_query")
        rows = self.config.get("locations", [])
        if not isinstance(rows, list):
            raise ValueError("invalid_locations")

        result: list[dict[str, Any]] = []
        needle = query.casefold()
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("invalid_location")
            name = row.get("name")
            if not isinstance(name, str):
                raise ValueError("invalid_location")
            if needle in name.casefold():
                result.append(
                    {
                        "id": row["id"],
                        "name": name,
                        **point(row),
                    }
                )
        return result

    def tracks(self) -> list[dict[str, Any]]:
        """Return track metadata without exposing its private sample list."""

        rows = self.config.get("tracks", [])
        if not isinstance(rows, list):
            raise ValueError("invalid_tracks")
        result: list[dict[str, Any]] = []
        for track in rows:
            if not isinstance(track, Mapping):
                raise ValueError("invalid_track")
            result.append(
                {
                    "id": track["id"],
                    "name": track["name"],
                    "description": track["description"],
                }
            )
        return result

    def rewind(self, track_id: str, instant: Any) -> dict[str, Any]:
        """Select the latest supplied sample at or before an aware instant.

        Samples are compared by parsed UTC time, so their order in the source
        fixture is not treated as chronological.  The source mapping is never
        sorted or modified, and the returned sample retains its original time
        representation while carrying the coordinates from that same row.
        """

        requested = _parse_instant(instant)
        tracks = self.config.get("tracks", [])
        if not isinstance(tracks, list):
            raise ValueError("invalid_tracks")

        selected_track: Mapping[str, Any] | None = None
        for track in tracks:
            if isinstance(track, Mapping) and track.get("id") == track_id:
                selected_track = track
                break
        if selected_track is None:
            raise LookupError("not_found")

        samples = selected_track.get("samples", [])
        if not isinstance(samples, list):
            raise ValueError("invalid_samples")

        # Keep the original list position as a deterministic tie-breaker for
        # duplicate timestamps without changing the fixture itself.
        candidates: list[tuple[datetime, int, Mapping[str, Any]]] = []
        for position, sample in enumerate(samples):
            if not isinstance(sample, Mapping):
                raise ValueError("invalid_sample")
            sample_time = _parse_instant(sample.get("time"))
            if sample_time <= requested:
                point(sample)
                candidates.append((sample_time, position, sample))

        if not candidates:
            raise LookupError("not_found")

        _, _, chosen = max(candidates, key=lambda item: (item[0], item[1]))
        selected_sample = {
            "time": chosen["time"],
            **point(chosen),
        }
        return {
            "id": selected_track["id"],
            "name": selected_track["name"],
            "description": selected_track["description"],
            "sample": selected_sample,
        }

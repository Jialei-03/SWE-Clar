"""Persistent storage and authorization for the meal component.

The HTTP layer resolves a bearer token to a user before calling this module.  The
methods below deliberately take that resolved user, rather than accepting a
user id from a request body.  Images are kept in SQLite as freshly encoded PNG
bytes so that an image id is never a path into the server's filesystem.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from PIL import Image


_REQUIRED_VENUE_FIELDS = ("name", "address", "latitude", "longitude")
_REQUIRED_POST_FIELDS = ("post_id", "image_id", "food", "caption")


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_nonempty_string(value: Any, error: str) -> str:
    if not _nonempty_string(value):
        raise ValueError(error)
    return value


def venue(value: Any) -> dict[str, Any]:
    """Validate and copy a complete venue supplied by a client/configuration.

    Coordinates intentionally use the ordinary JSON numeric types.  In
    particular, booleans are not coordinates even though bool is an int in
    Python.  The copy also prevents later mutation of the request/config from
    changing a value that is about to be stored.
    """

    if not isinstance(value, Mapping):
        raise ValueError("venue_required")

    if any(not _nonempty_string(value.get(key)) for key in ("name", "address")):
        raise ValueError("venue_required")

    coordinates: dict[str, float | int] = {}
    for key, limit in (("latitude", 90), ("longitude", 180)):
        number = value.get(key)
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(number)
            or not -limit <= number <= limit
        ):
            raise ValueError("invalid_coordinate")
        coordinates[key] = number

    return {
        "name": value["name"],
        "address": value["address"],
        "latitude": coordinates["latitude"],
        "longitude": coordinates["longitude"],
    }


class Store:
    """SQLite-backed image, post, feed, map and save store."""

    def __init__(self, path: str | Path, config: Mapping[str, Any]):
        self.path = str(path)
        self.config = config
        self._memory_connection: sqlite3.Connection | None = None

        # A persistent connection makes the useful ``Store(':memory:', ...)``
        # form work as expected in unit tests.  File-backed stores still use a
        # separate short-lived connection per operation, which also makes
        # restart persistence explicit.
        if self.path == ":memory:":
            self._memory_connection = sqlite3.connect(
                ":memory:", timeout=10, check_same_thread=False
            )
            self._configure_connection(self._memory_connection)
        else:
            parent = Path(self.path).parent
            if str(parent) not in ("", "."):
                parent.mkdir(parents=True, exist_ok=True)

        with self.db() as database:
            database.executescript(
                """
                CREATE TABLE IF NOT EXISTS images(
                    id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    png BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS posts(
                    id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    image TEXT NOT NULL REFERENCES images(id),
                    food TEXT NOT NULL,
                    caption TEXT NOT NULL,
                    venue TEXT NOT NULL,
                    created TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS saves(
                    owner TEXT NOT NULL,
                    post TEXT NOT NULL REFERENCES posts(id),
                    PRIMARY KEY(owner, post)
                );
                CREATE INDEX IF NOT EXISTS posts_created_idx
                    ON posts(created DESC, id ASC);
                CREATE INDEX IF NOT EXISTS posts_image_idx
                    ON posts(image);
                """
            )

    @staticmethod
    def _configure_connection(database: sqlite3.Connection) -> None:
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys=ON")

    def db(self) -> sqlite3.Connection:
        if self._memory_connection is not None:
            return self._memory_connection
        database = sqlite3.connect(self.path, timeout=10)
        self._configure_connection(database)
        return database

    def _known_user(self, user: Any) -> str:
        users = self.config.get("users", {})
        if not isinstance(user, str) or not isinstance(users, Mapping) or user not in users:
            raise PermissionError("denied")
        return user

    def actor(self, token: Any) -> str:
        """Resolve an opaque runtime token to the configured actor."""

        tokens = self.config.get("tokens", {})
        users = self.config.get("users", {})
        if (
            not isinstance(token, str)
            or not isinstance(tokens, Mapping)
            or not isinstance(users, Mapping)
        ):
            raise PermissionError("denied")
        identity = tokens.get(token)
        if not isinstance(identity, str) or identity not in users:
            raise PermissionError("denied")
        return identity

    def clock(self) -> str:
        """Return the host/configured clock as a normalized UTC ISO instant."""

        clock_file = self.config.get("clock_file")
        if clock_file:
            text = Path(clock_file).read_text(encoding="utf-8").strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            current = datetime.fromisoformat(text)
        else:
            current = datetime.now(timezone.utc)

        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("clock_timezone_required")
        return current.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _decode_upload(data: Any) -> bytes:
        if not isinstance(data, str) or not data:
            raise ValueError("image_required")

        encoded = data
        # The documented browser sends the part after the comma, but accepting
        # a conventional data URL is harmless and useful for direct clients.
        if encoded.startswith("data:"):
            header, separator, encoded = encoded.partition(",")
            if not separator or ";base64" not in header.lower():
                raise ValueError("invalid_image")

        # Whitespace is not emitted by the browser and accepting it would make
        # validation needlessly ambiguous, so use strict base64 validation.
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("invalid_image") from exc
        if not raw:
            raise ValueError("invalid_image")

        try:
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {"PNG", "JPEG"}:
                    raise ValueError("image_format")
                # Loading is important: Image.open alone only parses the
                # header and would allow a broken/truncated upload into the DB.
                source.load()

                # Work on a new image with an empty info dictionary.  This
                # retains decoded pixels while dropping EXIF, ICC, textual PNG
                # chunks and other source metadata.  PNG cannot represent
                # every Pillow mode, so convert only those exceptional modes.
                if "transparency" in source.info:
                    clean = source.convert("RGBA")
                elif source.mode in {"CMYK", "YCbCr"}:
                    clean = source.convert("RGB")
                elif source.mode not in {
                    "1",
                    "L",
                    "LA",
                    "I",
                    "I;16",
                    "P",
                    "RGB",
                    "RGBA",
                }:
                    clean = source.convert("RGBA" if "A" in source.mode else "RGB")
                else:
                    clean = source.copy()
                clean.info = {}

                output = io.BytesIO()
                clean.save(output, format="PNG")
                return output.getvalue()
        except ValueError:
            raise
        except Exception as exc:
            # Pillow has several exception classes depending on which decoder
            # rejected the bytes.  They are all an invalid client image here.
            raise ValueError("invalid_image") from exc

    def upload(self, user: str, action: Any) -> dict[str, str]:
        """Decode and persist an image owned by ``user``."""

        user = self._known_user(user)
        if not isinstance(action, Mapping):
            raise ValueError("body")
        png = self._decode_upload(action.get("data"))
        image_id = uuid.uuid4().hex

        with self.db() as database:
            database.execute(
                "INSERT INTO images(id, owner, png) VALUES (?, ?, ?)",
                (image_id, user, sqlite3.Binary(png)),
            )
        return {"image_id": image_id}

    def _configured_venue(self, venue_id: Any) -> dict[str, Any]:
        if not _nonempty_string(venue_id):
            raise ValueError("venue_required")
        venues = self.config.get("venues", {})
        if not isinstance(venues, Mapping) or venue_id not in venues:
            raise ValueError("venue_required")
        return venue(venues[venue_id])

    def _post_values(self, action: Any) -> tuple[str, str, str, str, dict[str, Any]]:
        if not isinstance(action, Mapping):
            raise ValueError("body")

        values: list[str] = []
        for key in _REQUIRED_POST_FIELDS:
            value = action.get(key)
            values.append(_require_nonempty_string(value, f"{key}_required"))

        has_configured = "venue_id" in action and action.get("venue_id") is not None
        has_manual = "venue" in action and action.get("venue") is not None
        if has_configured == has_manual:
            raise ValueError("venue_required")
        selected_venue = (
            self._configured_venue(action.get("venue_id"))
            if has_configured
            else venue(action.get("venue"))
        )
        return (*values, selected_venue)

    @staticmethod
    def _same_post(row: sqlite3.Row, image_id: str, food: str, caption: str, selected_venue: dict[str, Any]) -> bool:
        try:
            stored_venue = json.loads(row["venue"])
        except (TypeError, ValueError):
            return False
        return (
            row["image"] == image_id
            and row["food"] == food
            and row["caption"] == caption
            and stored_venue == selected_venue
        )

    def post(self, user_id: str, action: Any) -> dict[str, Any]:
        """Create a validated post, or return an identical owned retry."""

        user = self._known_user(user_id)
        post_id, image_id, food, caption, selected_venue = self._post_values(action)
        venue_json = json.dumps(
            selected_venue, sort_keys=True, separators=(",", ":"), allow_nan=False
        )

        with self.db() as database:
            # Serializing the id check and insert prevents two concurrent
            # requests from creating different records for one stable id.
            database.execute("BEGIN IMMEDIATE")
            existing = database.execute(
                "SELECT * FROM posts WHERE id = ?", (post_id,)
            ).fetchone()
            if existing is not None:
                if existing["owner"] != user:
                    raise PermissionError("post_denied")
                if not self._same_post(
                    existing, image_id, food, caption, selected_venue
                ):
                    raise ValueError("post_conflict")
                return self.record(existing, user, database)

            image = database.execute(
                "SELECT id, owner FROM images WHERE id = ?", (image_id,)
            ).fetchone()
            if image is None or image["owner"] != user:
                raise PermissionError("image_denied")

            created = self.clock()
            database.execute(
                """
                INSERT INTO posts(id, owner, image, food, caption, venue, created)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (post_id, user, image_id, food, caption, venue_json, created),
            )
            saved = database.execute(
                "SELECT * FROM posts WHERE id = ?", (post_id,)
            ).fetchone()
            return self.record(saved, user, database)

    def visible(self, user: str, owner: str) -> bool:
        user = self._known_user(user)
        if owner == user:
            return True
        profile = self.config["users"].get(user, {})
        follows = profile.get("follows", []) if isinstance(profile, Mapping) else []
        return isinstance(follows, (list, tuple, set)) and owner in follows

    def record(
        self, row: sqlite3.Row | Mapping[str, Any], user: str, database: sqlite3.Connection
    ) -> dict[str, Any]:
        user = self._known_user(user)
        result = {
            key: row[key] for key in ("id", "owner", "food", "caption", "created")
        }
        try:
            result["venue"] = json.loads(row["venue"])
        except (TypeError, ValueError) as exc:
            raise ValueError("stored_venue_invalid") from exc
        result["image_url"] = "/image/" + str(row["image"])
        result["can_save"] = row["owner"] != user
        result["saved"] = bool(
            database.execute(
                "SELECT 1 FROM saves WHERE owner = ? AND post = ?",
                (user, row["id"]),
            ).fetchone()
        )
        return result

    @staticmethod
    def _sort_created(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
        """Sort UTC ISO values by instant, with ascending ids for ties."""

        def key(row: sqlite3.Row) -> tuple[float, str]:
            text = row["created"]
            try:
                if isinstance(text, str) and text.endswith("Z"):
                    text = text[:-1] + "+00:00"
                instant = datetime.fromisoformat(text)
                if instant.tzinfo is None or instant.utcoffset() is None:
                    raise ValueError
                # Every value written by clock() is in UTC.  timestamp() also
                # makes the ordering correct if an older DB contains an offset.
                moment = instant.astimezone(timezone.utc).timestamp()
            except (TypeError, ValueError, OverflowError):
                # A malformed pre-existing row should not make a feed request
                # crash; it sorts after valid records while retaining its id.
                moment = float("-inf")
            return (-moment, str(row["id"]))

        return sorted(rows, key=key)

    def feed(self, user: str) -> list[dict[str, Any]]:
        user = self._known_user(user)
        with self.db() as database:
            rows = database.execute("SELECT * FROM posts").fetchall()
            rows = [row for row in rows if self.visible(user, row["owner"])]
            rows = self._sort_created(rows)
            return [self.record(row, user, database) for row in rows]

    def save(self, user: str, action: Any) -> dict[str, Any]:
        user = self._known_user(user)
        if not isinstance(action, Mapping):
            raise ValueError("body")
        post_id = action.get("post_id")
        if not _nonempty_string(post_id):
            raise ValueError("post_required")
        saved = action.get("saved")
        if not isinstance(saved, bool):
            raise ValueError("saved_boolean_required")

        with self.db() as database:
            row = database.execute(
                "SELECT * FROM posts WHERE id = ?", (post_id,)
            ).fetchone()
            if (
                row is None
                or row["owner"] == user
                or not self.visible(user, row["owner"])
            ):
                raise PermissionError("save_denied")
            if saved:
                database.execute(
                    "INSERT OR IGNORE INTO saves(owner, post) VALUES (?, ?)",
                    (user, row["id"]),
                )
            else:
                database.execute(
                    "DELETE FROM saves WHERE owner = ? AND post = ?",
                    (user, row["id"]),
                )
            return self.record(row, user, database)

    def pins(self, user: str, mode: str) -> list[dict[str, Any]]:
        user = self._known_user(user)
        if mode not in {"personal", "friends"}:
            raise ValueError("map_mode")

        with self.db() as database:
            rows = database.execute("SELECT * FROM posts").fetchall()
            if mode == "personal":
                selected = [row for row in rows if row["owner"] == user]
            else:
                selected = [
                    row
                    for row in rows
                    if row["owner"] != user and self.visible(user, row["owner"])
                ]
            selected = self._sort_created(selected)

            result: list[dict[str, Any]] = []
            for row in selected:
                try:
                    stored_venue = json.loads(row["venue"])
                    selected_venue = venue(stored_venue)
                except (TypeError, ValueError) as exc:
                    raise ValueError("stored_venue_invalid") from exc
                result.append(
                    {
                        "post_id": row["id"],
                        "food": row["food"],
                        **selected_venue,
                    }
                )
            return result

    def image(self, user: str, ident: Any) -> bytes:
        user = self._known_user(user)
        if not _nonempty_string(ident):
            raise PermissionError("image_denied")

        with self.db() as database:
            row = database.execute(
                "SELECT id, owner, png FROM images WHERE id = ?", (ident,)
            ).fetchone()
            if row is None:
                raise PermissionError("image_denied")

            if row["owner"] != user:
                shared = any(
                    self.visible(user, post["owner"])
                    for post in database.execute(
                        "SELECT owner FROM posts WHERE image = ?", (ident,)
                    )
                )
                if not shared:
                    raise PermissionError("image_denied")
            return bytes(row["png"])

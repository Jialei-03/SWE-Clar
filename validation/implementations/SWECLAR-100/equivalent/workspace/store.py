"""Persistent catalogue and managed-device boundary.

The values accepted by this module are deliberately split into two groups:
``actor`` values are produced by the authentication adapter (and therefore
come from the private runtime configuration), while values in ``action`` are
untrusted request data.  No permission or identity decision is made from an
action field.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from os import PathLike
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


_EDIT_ROLES = {"editor", "admin"}
_VIEW_ROLES = {"device", "editor", "admin"}


class Store:
    """SQLite-backed draft, publication, analytics, and bridge store."""

    def __init__(self, path: str | Path, config: dict[str, Any]):
        self.path = str(path)
        # sqlite normally creates a separate database for every connection to
        # ':memory:'.  Use a private shared-memory URI plus a keeper so the
        # short-lived connections used by this class see the same schema.
        self._memory_uri = None
        self._memory_keeper = None
        if self.path == ":memory:":
            self._memory_uri = f"file:kiosk-store-{id(self)}?mode=memory&cache=shared"
            self._memory_keeper = sqlite3.connect(self._memory_uri, uri=True, timeout=10)
        # Keep the configuration private to this process.  In particular, it
        # is never copied into a catalogue response or a browser bundle.
        self.config = config if isinstance(config, dict) else {}
        with self.db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS draft(
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS publications(
                    version INTEGER PRIMARY KEY,
                    change_id TEXT UNIQUE NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events(
                    id TEXT PRIMARY KEY,
                    device TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                """
            )
            db.execute(
                "INSERT OR IGNORE INTO draft(id,payload) VALUES (1,?)",
                (json.dumps({"categories": [], "products": []}),),
            )

    def db(self) -> sqlite3.Connection:
        """Open a short-lived connection with busy handling for concurrent HTTP requests."""

        if self._memory_uri is not None:
            return sqlite3.connect(self._memory_uri, uri=True, timeout=10)
        return sqlite3.connect(self.path, timeout=10)

    # ------------------------------------------------------------------
    # Authentication/configuration helpers
    # ------------------------------------------------------------------
    def actor(self, token: str | None) -> dict[str, str]:
        """Resolve a bearer token using only the private runtime config.

        Returning just the two identity fields also prevents accidental
        exposure of any additional private token metadata in callers.
        """

        tokens = self.config.get("tokens", {})
        if not isinstance(tokens, dict) or not isinstance(token, str):
            raise PermissionError("denied")
        configured = tokens.get(token)
        if not isinstance(configured, dict):
            raise PermissionError("denied")
        identity = configured.get("id")
        role = configured.get("role")
        if not isinstance(identity, str) or not identity or not isinstance(role, str):
            raise PermissionError("denied")
        return {"id": identity, "role": role}

    @staticmethod
    def _require_role(actor: Any, roles: set[str]) -> dict[str, str]:
        if not isinstance(actor, dict):
            raise PermissionError("denied")
        role = actor.get("role")
        identity = actor.get("id")
        if role not in roles or not isinstance(identity, str) or not identity:
            raise PermissionError("denied")
        # Never retain a caller-owned actor dictionary in a record.
        return {"id": identity, "role": role}

    def _configured_assets(self) -> dict[str, str]:
        assets = self.config.get("assets", {})
        if not isinstance(assets, dict):
            return {}
        # Asset paths are accepted only from configuration, never from an
        # edit action.  Ignore malformed private config entries here; a
        # reference to one will be rejected by _asset_bytes.
        return {
            key: str(value)
            for key, value in assets.items()
            if isinstance(key, str) and isinstance(value, (str, PathLike))
        }

    def _device_ids(self) -> set[str]:
        tokens = self.config.get("tokens", {})
        if not isinstance(tokens, dict):
            return set()
        result: set[str] = set()
        for configured in tokens.values():
            if (
                isinstance(configured, dict)
                and configured.get("role") == "device"
                and isinstance(configured.get("id"), str)
                and configured["id"]
            ):
                result.add(configured["id"])
        return result

    # ------------------------------------------------------------------
    # JSON/draft helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _copy_json(value: Any) -> Any:
        """Make a detached JSON-compatible copy and reject non-JSON values."""

        try:
            return json.loads(json.dumps(value))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("invalid_json") from exc

    @staticmethod
    def _load_payload(raw: str | None) -> dict[str, Any]:
        try:
            value = json.loads(raw or "")
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid_catalogue") from exc
        if not isinstance(value, dict):
            raise ValueError("invalid_catalogue")
        categories = value.get("categories")
        products = value.get("products")
        if not isinstance(categories, list) or not isinstance(products, list):
            raise ValueError("invalid_catalogue")
        return {"categories": categories, "products": products}

    def _draft(self, db: sqlite3.Connection) -> dict[str, Any]:
        row = db.execute("SELECT payload FROM draft WHERE id=1").fetchone()
        if row is None:
            raise ValueError("invalid_catalogue")
        return self._load_payload(row[0])

    @staticmethod
    def _nonempty_string(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    def _validate_record_shape(self, kind: Any, record: Any) -> dict[str, Any]:
        if kind not in ("categories", "products") or not isinstance(record, dict):
            raise ValueError("invalid_record")

        # Validate without normalising the values: a successful edit returns
        # the caller's catalogue fields, while still enforcing the schema.
        if not self._nonempty_string(record.get("id")):
            raise ValueError("invalid_record")
        order = record.get("order")
        # bool is an int subclass, but is not an integer catalogue order.
        if isinstance(order, bool) or not isinstance(order, int):
            raise ValueError("invalid_record")
        text = record.get("text")
        if not isinstance(text, dict):
            raise ValueError("invalid_record")
        if not self._nonempty_string(text.get("en")) or not self._nonempty_string(
            text.get("es")
        ):
            raise ValueError("invalid_record")

        if kind == "products":
            if not self._nonempty_string(record.get("category_id")):
                raise ValueError("invalid_record")
            if not self._nonempty_string(record.get("asset_id")):
                raise ValueError("invalid_record")

        return self._copy_json(record)

    @staticmethod
    def _replace_record(records: list[Any], record: dict[str, Any]) -> list[Any]:
        """Upsert by ID while preserving every unrelated record and order."""

        result = list(records)
        record_id = record["id"]
        for index, existing in enumerate(result):
            if isinstance(existing, dict) and existing.get("id") == record_id:
                result[index] = record
                return result
        result.append(record)
        return result

    # ------------------------------------------------------------------
    # Catalogue editing/publication
    # ------------------------------------------------------------------
    def edit(self, actor: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        """Validate and atomically upsert one draft catalogue record."""

        self._require_role(actor, _EDIT_ROLES)
        if not isinstance(action, dict):
            raise ValueError("invalid_request")

        kind = action.get("kind")
        # Only the documented action fields are consulted.  In particular,
        # action['actor'] and action['role'] cannot grant edit permission.
        record = self._validate_record_shape(kind, action.get("record"))

        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            draft = self._draft(db)
            if kind == "products":
                category_ids = {
                    item.get("id")
                    for item in draft["categories"]
                    if isinstance(item, dict)
                }
                if record["category_id"] not in category_ids:
                    raise ValueError("unknown_category")
                if record["asset_id"] not in self._configured_assets():
                    raise ValueError("unknown_asset")

            draft[kind] = self._replace_record(draft[kind], record)
            payload = json.dumps(draft, ensure_ascii=False, separators=(",", ":"))
            db.execute("UPDATE draft SET payload=? WHERE id=1", (payload,))

        return copy.deepcopy(record)

    def _asset_bytes(self, asset_id: str) -> bytes:
        """Read an image only through an ID mapped by private configuration."""

        assets = self._configured_assets()
        path = assets.get(asset_id)
        if path is None:
            raise KeyError("unknown_asset")
        try:
            return Path(path).read_bytes()
        except (OSError, ValueError) as exc:
            # Do not return a filesystem path in an error or HTTP response.
            raise ValueError("asset_unavailable") from exc

    @staticmethod
    def _asset_url(asset_id: str) -> str:
        return "/asset/" + urllib.parse.quote(asset_id, safe="")

    def _asset_metadata(self, asset_id: str) -> dict[str, str]:
        data = self._asset_bytes(asset_id)
        return {
            "url": self._asset_url(asset_id),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    def _make_snapshot(self, draft: dict[str, Any], version: int) -> dict[str, Any]:
        """Build a detached publication and its checksums from the draft."""

        categories = self._copy_json(draft["categories"])
        products = self._copy_json(draft["products"])

        # Revalidate the complete draft at publication time.  This protects a
        # database created by an older version as well as ordinary edits.
        category_ids: set[str] = set()
        for category in categories:
            if not isinstance(category, dict):
                raise ValueError("invalid_catalogue")
            if not self._nonempty_string(category.get("id")):
                raise ValueError("invalid_catalogue")
            if category["id"] in category_ids:
                raise ValueError("invalid_catalogue")
            category_ids.add(category["id"])
            self._validate_record_shape("categories", category)

        referenced: set[str] = set()
        product_ids: set[str] = set()
        for product in products:
            if not isinstance(product, dict):
                raise ValueError("invalid_catalogue")
            self._validate_record_shape("products", product)
            if product["id"] in product_ids:
                raise ValueError("invalid_catalogue")
            product_ids.add(product["id"])
            if product["category_id"] not in category_ids:
                raise ValueError("unknown_category")
            if product["asset_id"] not in self._configured_assets():
                raise ValueError("unknown_asset")
            referenced.add(product["asset_id"])

        assets = {
            asset_id: self._asset_metadata(asset_id)
            for asset_id in __import__('control_algorithms').stable_order(referenced)
        }
        return {
            "version": version,
            "categories": categories,
            "products": products,
            "assets": assets,
        }

    def publish(self, actor: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        """Publish one immutable snapshot for a unique change ID."""

        self._require_role(actor, _EDIT_ROLES)
        if not isinstance(action, dict):
            raise ValueError("invalid_request")
        change_id = action.get("change_id")
        if not self._nonempty_string(change_id):
            raise ValueError("invalid_change_id")

        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT payload FROM publications WHERE change_id=?", (change_id,)
            ).fetchone()
            if existing is not None:
                # A retry is idempotent, even if the draft has subsequently
                # moved on.  Return a fresh object so callers cannot mutate DB
                # state through the result.
                return self._copy_json(json.loads(existing[0]))

            draft = self._draft(db)
            current = db.execute(
                "SELECT COALESCE(MAX(version),0) FROM publications"
            ).fetchone()
            version = int(current[0]) + 1
            snapshot = self._make_snapshot(draft, version)
            db.execute(
                "INSERT INTO publications(version,change_id,payload) VALUES (?,?,?)",
                (
                    version,
                    change_id,
                    json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        return copy.deepcopy(snapshot)

    def snapshot(self, actor: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return the newest immutable publication, or an empty version zero."""

        with self.db() as db:
            row = db.execute(
                "SELECT payload FROM publications ORDER BY version DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return {"version": 0, "categories": [], "products": [], "assets": {}}
        value = self._copy_json(json.loads(row[0]))
        # A publication created by this class always has this shape.  Keep the
        # method defensive for a database supplied by an older process.
        if not isinstance(value, dict):
            raise ValueError("invalid_catalogue")
        return value

    def asset_bytes(self, actor: dict[str, Any] | None, asset_id: str) -> bytes:
        """Return an image only when its ID belongs to the latest publication."""

        snapshot = self.snapshot(actor)
        assets = snapshot.get("assets", {})
        if not isinstance(assets, dict) or asset_id not in assets:
            raise KeyError("unknown_asset")
        return self._asset_bytes(asset_id)

    # ------------------------------------------------------------------
    # Analytics and managed-device bridge
    # ------------------------------------------------------------------
    def track(self, actor: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        identity = self._require_role(actor, {"device"})
        if not isinstance(action, dict):
            raise ValueError("invalid_request")

        snapshot = self.snapshot(identity)
        target_type = action.get("target_type")
        target_id = action.get("target_id")
        event_id = action.get("event_id")
        if not self._nonempty_string(event_id):
            raise ValueError("invalid_event")
        if not isinstance(target_type, str) or not isinstance(target_id, str):
            raise ValueError("invalid_target")

        categories = snapshot.get("categories", [])
        products = snapshot.get("products", [])
        known: dict[str, set[str]] = {
            "page": {"home"},
            "category": {
                item["id"]
                for item in categories
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            },
            "product": {
                item["id"]
                for item in products
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            },
        }
        if target_type not in known or target_id not in known[target_type]:
            raise ValueError("invalid_target")

        # The authenticated configuration identity is authoritative; an
        # action['device_id'] field, if present, is intentionally ignored.
        record = {
            "event_id": event_id,
            "target_type": target_type,
            "target_id": target_id,
            "device_id": identity["id"],
        }
        encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT device,payload FROM events WHERE id=?", (event_id,)
            ).fetchone()
            if old is not None:
                try:
                    old_record = json.loads(old[1])
                except (TypeError, ValueError) as exc:
                    raise ValueError("event_conflict") from exc
                if old[0] != identity["id"] or old_record != record:
                    raise ValueError("event_conflict")
                return copy.deepcopy(record)
            db.execute(
                "INSERT INTO events(id,device,payload) VALUES (?,?,?)",
                (event_id, identity["id"], encoded),
            )
        return record

    def analytics(self, actor: dict[str, Any]) -> list[dict[str, Any]]:
        self._require_role(actor, _EDIT_ROLES)
        with self.db() as db:
            rows = db.execute("SELECT payload FROM events ORDER BY rowid").fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(row[0])
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid_event") from exc
            if isinstance(value, dict):
                result.append(value)
        return result

    def settings(self, actor: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        self._require_role(actor, {"admin"})
        if not isinstance(action, dict):
            raise ValueError("invalid_request")
        device_id = action.get("device_id")
        if not isinstance(device_id, str) or device_id not in self._device_ids():
            raise ValueError("unknown_device")

        settings_url = self.config.get("settings_url")
        if not isinstance(settings_url, str):
            raise ValueError("fixture_endpoint_required")
        parsed = urllib.parse.urlsplit(settings_url)
        # The supplied connector is intentionally a local HTTP boundary.  Do
        # not turn a private configuration value into an arbitrary server-side
        # request primitive.
        if parsed.scheme.lower() != "http" or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError("fixture_endpoint_required")

        body = json.dumps(
            {"device_id": device_id, "operation": "open_network_settings"},
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            settings_url,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=3) as response:
                if not 200 <= getattr(response, "status", 200) < 300:
                    raise ValueError("settings_not_opened")
                value = json.load(response)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("settings_not_opened") from exc

        # Exact matching of both fields makes a response for another device,
        # or an acknowledgement of another operation, unsuccessful.
        if (
            not isinstance(value, dict)
            or set(value) != {"device_id", "opened"}
            or value.get("device_id") != device_id
            or type(value.get("opened")) is not bool
            or value.get("opened") is not True
        ):
            raise ValueError("settings_not_opened")
        return value

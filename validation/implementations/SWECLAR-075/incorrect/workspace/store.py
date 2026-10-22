"""SQLite-backed account and attendance store.

The HTTP layer deliberately keeps authentication and routing concerns out of
this module.  The store is the authority for password verification, session
revocation, location checks, and the attendance interval state machine.
"""

import base64
import contextlib
import hashlib
import hmac
import json
import math
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Mapping

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class Error(Exception):
    """An expected, safe-to-return application error."""

    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def _finite_number(value: Any, error: str) -> float:
    """Convert a number-like input while rejecting booleans and non-finite data."""

    if isinstance(value, bool):
        raise Error(error)
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise Error(error) from None
    if not math.isfinite(result):
        raise Error(error)
    return result


def distance(lat: Any, lon: Any, site: Mapping[str, Any]) -> float:
    """Return the great-circle distance to a configured site in metres.

    The caller's coordinates are validated here rather than relying on the
    browser or on any asserted distance value.  ``math.remainder`` keeps the
    longitude delta on the shortest path, including the +/-180 degree edge.
    """

    latitude = _finite_number(lat, "invalid_location")
    longitude = _finite_number(lon, "invalid_location")
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        raise Error("invalid_location")

    try:
        site_latitude = _finite_number(site["latitude"], "invalid_site")
        site_longitude = _finite_number(site["longitude"], "invalid_site")
    except (KeyError, TypeError):
        raise Error("invalid_site", 500) from None
    if (
        not -90.0 <= site_latitude <= 90.0
        or not -180.0 <= site_longitude <= 180.0
    ):
        raise Error("invalid_site", 500)

    p1 = math.radians(latitude)
    p2 = math.radians(site_latitude)
    delta_latitude = p2 - p1
    delta_longitude = math.radians(
        math.remainder(site_longitude - longitude, 360.0)
    )
    haversine = (
        math.sin(delta_latitude / 2.0) ** 2
        + math.cos(p1)
        * math.cos(p2)
        * math.sin(delta_longitude / 2.0) ** 2
    )
    # Rounding can move a value infinitesimally outside [0, 1].
    haversine = min(1.0, max(0.0, haversine))
    return 6371008.8 * 2.0 * math.asin(math.sqrt(haversine))


class Store:
    """Persistent account, session, and attendance state."""

    SCRYPT_N = 16_384
    SCRYPT_R = 8
    SCRYPT_P = 1
    SCRYPT_DKLEN = 32
    AAD = b"checkin-fixture"

    def __init__(
        self,
        path: str,
        config: Mapping[str, Any],
        clock: Callable[[], Any] | None = None,
    ):
        self.path = path
        self.config = config
        try:
            self.key = bytes.fromhex(str(config["encryption_key"]))
        except (KeyError, TypeError, ValueError):
            raise ValueError("configuration requires a hexadecimal encryption_key") from None
        if len(self.key) != 32:
            raise ValueError("encryption_key must be 32 bytes")
        self.crypto = AESGCM(self.key)
        self.clock = clock or (lambda: datetime.now(timezone.utc).timestamp())

        with self.db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users(
                    id TEXT PRIMARY KEY,
                    lookup TEXT UNIQUE NOT NULL,
                    email TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    verifier TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS sessions(
                    hash TEXT PRIMARY KEY,
                    user TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS intervals(
                    id TEXT PRIMARY KEY,
                    user TEXT NOT NULL,
                    record TEXT NOT NULL,
                    open INTEGER NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_open
                    ON intervals(user) WHERE open=1;
                """
            )

    @contextlib.contextmanager
    def db(self) -> Iterator[sqlite3.Connection]:
        """Open a short-lived connection with a bounded lock wait."""

        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _normalize_email(value: Any) -> str:
        if not isinstance(value, str):
            raise Error("invalid_account")
        email = value.strip().lower()
        if not email or "@" not in email or len(email) > 320:
            raise Error("invalid_account")
        return email

    @staticmethod
    def _password(value: Any, *, registration: bool) -> str:
        if not isinstance(value, str):
            if registration:
                raise Error("invalid_account")
            raise Error("invalid_credentials", 403)
        if registration and not 8 <= len(value) <= 1024:
            raise Error("invalid_account")
        if not registration and not value:
            raise Error("invalid_credentials", 403)
        return value

    def _lookup_normalized(self, email: str) -> str:
        return hmac.new(self.key, email.encode("utf-8"), hashlib.sha256).hexdigest()

    def lookup(self, email: str) -> str:
        """Return the keyed lookup value for a normalized account email."""

        return self._lookup_normalized(self._normalize_email(email))

    @classmethod
    def _derive(cls, password: str, salt: bytes) -> bytes:
        # hashlib.scrypt is intentionally used rather than a fast bare hash.
        return hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=cls.SCRYPT_N,
            r=cls.SCRYPT_R,
            p=cls.SCRYPT_P,
            dklen=cls.SCRYPT_DKLEN,
        )

    def seal(self, data: Any) -> str:
        """Encrypt JSON data with a fresh nonce and the fixture AAD."""

        nonce = secrets.token_bytes(12)
        payload = json.dumps(
            data, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        ciphertext = self.crypto.encrypt(nonce, payload, self.AAD)
        return base64.b64encode(nonce + ciphertext).decode("ascii")

    def unseal(self, data: str) -> Any:
        blob = base64.b64decode(data, validate=True)
        if len(blob) < 12 + 16:
            raise ValueError("invalid encrypted payload")
        return json.loads(self.crypto.decrypt(blob[:12], blob[12:], self.AAD))

    def register(self, action: Mapping[str, Any]) -> dict[str, str]:
        if not isinstance(action, Mapping):
            raise Error("invalid_request")
        email = self._normalize_email(action.get("email"))
        password = self._password(action.get("password"), registration=True)
        salt = secrets.token_bytes(16)
        verifier = self._derive(password, salt).hex()
        user_id = secrets.token_hex(16)

        try:
            with self.db() as db:
                db.execute(
                    """
                    INSERT INTO users(id,lookup,email,salt,verifier,active)
                    VALUES(?,?,?,?,?,1)
                    """,
                    (
                        user_id,
                        self._lookup_normalized(email),
                        self.seal(email),
                        salt.hex(),
                        verifier,
                    ),
                )
        except sqlite3.IntegrityError:
            # The unique lookup is over the normalized form, so this also
            # handles concurrent registration of differently-cased spellings.
            raise Error("duplicate_account", 409) from None
        return {"id": user_id, "email": email}

    @staticmethod
    def _session_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def login(self, action: Mapping[str, Any]) -> str:
        if not isinstance(action, Mapping):
            raise Error("invalid_credentials", 403)
        try:
            email = self._normalize_email(action.get("email"))
        except Error:
            raise Error("invalid_credentials", 403) from None
        try:
            password = self._password(action.get("password"), registration=False)
        except Error:
            raise

        with self.db() as db:
            row = db.execute(
                "SELECT id,salt,verifier,active FROM users WHERE lookup=?",
                (self._lookup_normalized(email),),
            ).fetchone()
            if not row or not row[3]:
                raise Error("invalid_credentials", 403)
            try:
                salt = bytes.fromhex(row[1])
                candidate = self._derive(password, salt).hex()
            except (TypeError, ValueError):
                raise Error("invalid_credentials", 403) from None
            if not hmac.compare_digest(candidate, row[2]):
                raise Error("invalid_credentials", 403)

            # The random bearer value is returned only to the HTTP layer so it
            # can be placed in an HttpOnly cookie.  SQLite stores only its hash.
            for _ in range(3):
                token = secrets.token_urlsafe(32)
                try:
                    db.execute(
                        "INSERT INTO sessions(hash,user) VALUES(?,?)",
                        (self._session_hash(token), row[0]),
                    )
                    return token
                except sqlite3.IntegrityError:
                    continue
            raise Error("session_unavailable", 503)

    def actor(self, token: str) -> dict[str, str]:
        if not isinstance(token, str) or not token:
            raise Error("auth_required", 403)
        with self.db() as db:
            row = db.execute(
                """
                SELECT u.id,u.email
                FROM sessions AS s
                JOIN users AS u ON u.id=s.user
                WHERE s.hash=? AND u.active=1
                """,
                (self._session_hash(token),),
            ).fetchone()
        if not row:
            raise Error("auth_required", 403)
        try:
            email = self.unseal(row[1])
        except Exception:
            # Do not expose corruption details or an encrypted field.
            raise Error("auth_required", 403) from None
        if not isinstance(email, str):
            raise Error("auth_required", 403)
        return {"id": row[0], "email": email}

    def logout(self, token: str) -> dict[str, bool]:
        if isinstance(token, str) and token:
            with self.db() as db:
                db.execute(
                    "DELETE FROM sessions WHERE hash=?",
                    (self._session_hash(token),),
                )
        return {"ok": True}

    def _active_site(self, site_id: str) -> Mapping[str, Any]:
        sites = self.config.get("sites", [])
        if not isinstance(sites, list):
            raise Error("invalid_site", 500)
        for site in sites:
            if isinstance(site, Mapping) and site.get("id") == site_id:
                if not site.get("active"):
                    raise Error("site_inactive", 409)
                try:
                    radius = _finite_number(site["radius_m"], "invalid_site")
                except (KeyError, TypeError):
                    raise Error("invalid_site", 500) from None
                if radius < 0:
                    raise Error("invalid_site", 500)
                # Validate configuration before accepting a check-in.  The
                # public site endpoint only exposes the configured values.
                distance(site["latitude"], site["longitude"], site)
                return site
        raise Error("site_not_found", 404)

    @staticmethod
    def _checkin_values(action: Mapping[str, Any]) -> tuple[str, str, float, float]:
        if not isinstance(action, Mapping):
            raise Error("invalid_request")
        event_id = action.get("id")
        site_id = action.get("site_id")
        if (
            not isinstance(event_id, str)
            or not event_id.strip()
            or len(event_id) > 256
            or not isinstance(site_id, str)
            or not site_id.strip()
            or len(site_id) > 256
        ):
            raise Error("invalid_checkin")
        latitude = _finite_number(action.get("latitude"), "invalid_location")
        longitude = _finite_number(action.get("longitude"), "invalid_location")
        if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
            raise Error("invalid_location")
        return event_id, site_id, latitude, longitude

    def _now(self) -> float:
        try:
            now = _finite_number(self.clock(), "clock_unavailable")
        except Error:
            raise Error("clock_unavailable", 503) from None
        return now

    def checkin(self, user_id: str, action: Mapping[str, Any]) -> dict[str, Any]:
        """Persist an in-radius open attendance interval.

        A write transaction covers the idempotency lookup, open-interval
        check, and insert.  The partial unique index is a second line of
        defence for the one-open-interval rule.
        """

        if not isinstance(user_id, str) or not user_id:
            raise Error("auth_required", 403)
        event_id, site_id, latitude, longitude = self._checkin_values(action)

        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")

            existing = db.execute(
                "SELECT user,record FROM intervals WHERE id=?", (event_id,)
            ).fetchone()
            if existing:
                if existing[0] != user_id:
                    raise Error("event_id_conflict", 409)
                record = self.unseal(existing[1])
                if not isinstance(record, dict) or record.get("site_id") != site_id:
                    raise Error("event_id_conflict", 409)
                # A retry of the same actor/site event is idempotent.  In
                # particular, it never creates a second interval.
                return record

            site = self._active_site(site_id)
            if distance(latitude, longitude, site) >= _finite_number(
                site["radius_m"], "invalid_site"
            ):
                raise Error("outside_radius", 403)

            open_row = db.execute(
                "SELECT 1 FROM intervals WHERE user=? AND open=1 LIMIT 1",
                (user_id,),
            ).fetchone()
            if open_row:
                raise Error("already_checked_in", 409)

            started_at = self._now()
            record = {
                "id": event_id,
                "user_id": user_id,
                "site_id": site_id,
                "latitude": latitude,
                "longitude": longitude,
                "started_at": started_at,
                "ended_at": None,
                "duration_seconds": None,
            }
            try:
                db.execute(
                    "INSERT INTO intervals(id,user,record,open) VALUES(?,?,?,1)",
                    (event_id, user_id, self.seal(record)),
                )
            except sqlite3.IntegrityError:
                # BEGIN IMMEDIATE normally makes this unreachable, but retain
                # a safe application error if an existing database has a
                # conflicting constraint.
                raise Error("checkin_conflict", 409) from None
            return record

    def checkout(self, user_id: str) -> dict[str, Any]:
        if not isinstance(user_id, str) or not user_id:
            raise Error("auth_required", 403)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id,record FROM intervals WHERE user=? AND open=1",
                (user_id,),
            ).fetchone()
            if not row:
                raise Error("no_open_interval", 409)

            record = self.unseal(row[1])
            try:
                started_at = _finite_number(record["started_at"], "invalid_record")
            except (KeyError, TypeError):
                raise Error("invalid_record", 500) from None
            now = self._now()
            if now < started_at:
                # Raising inside the transaction rolls it back, leaving the
                # original open encrypted record untouched.
                raise Error("clock_regression", 409)
            duration = now - started_at
            if duration < 0:  # defensive guard against floating point changes
                raise Error("clock_regression", 409)
            record["ended_at"] = now
            record["duration_seconds"] = max(0.0, duration)
            db.execute(
                "UPDATE intervals SET record=?,open=0 WHERE id=? AND open=1",
                (self.seal(record), row[0]),
            )
            return record

    def history(self, user_id: str) -> list[dict[str, Any]]:
        if not isinstance(user_id, str) or not user_id:
            raise Error("auth_required", 403)
        with self.db() as db:
            rows = db.execute(
                "SELECT record FROM intervals WHERE user=? ORDER BY rowid",
                (user_id,),
            ).fetchall()
        records: list[dict[str, Any]] = []
        for (payload,) in rows:
            record = self.unseal(payload)
            if isinstance(record, dict):
                records.append(record)
        return records

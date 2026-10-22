"""Transactional SQLite persistence for V4 sessions and worker state."""

from __future__ import annotations

import copy
import json
import re
import sqlite3
import threading
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .canonical import canonical_bytes


_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SQLITE_WRITE_LOCKS_GUARD = threading.Lock()
_SQLITE_WRITE_LOCKS: dict[str, threading.RLock] = {}


def _sqlite_write_lock(path: Path) -> threading.RLock:
    """Return one process-wide writer lock for a SQLite database path."""

    key = str(path.resolve())
    with _SQLITE_WRITE_LOCKS_GUARD:
        return _SQLITE_WRITE_LOCKS.setdefault(key, threading.RLock())


class _SerializedSQLiteConnection(sqlite3.Connection):
    """Queue ``BEGIN IMMEDIATE`` transactions before they enter SQLite.

    The evaluation worker creates repository objects per request.  SQLite's
    busy timeout alone lets dozens of Python threads pile up at the database
    writer lock and eventually fail.  A path-scoped process lock preserves
    the existing short transactions while making the queue explicit and
    lossless.
    """

    _sweclar_write_lock: threading.RLock | None = None
    _sweclar_write_lock_held = False

    def configure_write_lock(self, lock: threading.RLock) -> None:
        self._sweclar_write_lock = lock

    def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
        begin_immediate = sql.lstrip().casefold().startswith("begin immediate")
        if begin_immediate and not self._sweclar_write_lock_held:
            if self._sweclar_write_lock is None:
                raise RuntimeError("SQLite write lock was not configured")
            self._sweclar_write_lock.acquire()
            self._sweclar_write_lock_held = True
        try:
            return super().execute(sql, parameters)
        except Exception:
            if begin_immediate:
                self._release_write_lock()
            raise

    def commit(self) -> None:
        try:
            super().commit()
        finally:
            self._release_write_lock()

    def rollback(self) -> None:
        try:
            super().rollback()
        finally:
            self._release_write_lock()

    def close(self) -> None:
        try:
            super().close()
        finally:
            self._release_write_lock()

    def _release_write_lock(self) -> None:
        if self._sweclar_write_lock_held and self._sweclar_write_lock is not None:
            self._sweclar_write_lock_held = False
            self._sweclar_write_lock.release()


class StorageError(Exception):
    """Base class for repository failures."""


class SessionNotFound(StorageError, KeyError):
    """Raised when a requested session does not exist."""


class SessionAlreadyExists(StorageError):
    """Raised when creating a duplicate session."""




class ProfileRecordAlreadyExists(StorageError):
    """Raised when creating a duplicate configuration profile."""






class RevisionConflict(StorageError):
    """Raised when a compare-and-swap uses a stale revision."""


class OperationNotFound(StorageError, KeyError):
    """Raised when a requested operation does not exist."""


class OperationConflict(StorageError):
    """Raised when an operation identifier or terminal result conflicts."""


class IdempotencyConflict(StorageError):
    """Raised when an idempotency key is reused for another request."""


class LeaseConflict(StorageError):
    """Raised when a live branch lease belongs to another worker attempt."""


@dataclass(frozen=True, slots=True)
class OperationRecord:
    operation_id: str
    session_id: str
    stage: str
    status: str
    attempt: int
    idempotency_key: str | None
    error: Any
    result: Any
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BranchLease:
    session_id: str
    branch: str
    owner_id: str
    attempt: int
    acquired_at: datetime
    expires_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: int
    session_id: str
    actor: str
    action: str
    details: Any
    operation_id: str | None
    created_at: datetime


class SessionRepository:
    """Persist V4 state through short, independent SQLite transactions."""

    def __init__(
        self, db_path: str | Path, *, clock: Callable[[], datetime] | None = None
    ) -> None:
        self.db_path = Path(db_path)
        self._clock = _utc_now if clock is None else clock
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def create_session(self, record: Mapping[str, Any] | Any) -> dict[str, Any]:
        document = _document_from(record)
        for field in ("session_id", "phase", "status"):
            if not isinstance(document.get(field), str) or not document[field]:
                raise ValueError(f"session {field} must be a non-empty string")
        if document.get("revision", 0) != 0:
            raise ValueError("new session revision must be 0")
        document["revision"] = 0
        document_json = canonical_bytes(document)
        now = self._now()
        timestamp = _format_datetime(now)

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO sessions(
                    session_id, document_json, phase, status, experiment_version,
                    revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    document["session_id"],
                    document_json,
                    document["phase"],
                    document["status"],
                    _experiment_version(document),
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise SessionAlreadyExists(document["session_id"]) from error
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return copy.deepcopy(document)

    def get_session(self, session_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT document_json, phase, status, revision
                FROM sessions WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            raise SessionNotFound(session_id)
        document = _decode_json(row["document_json"])
        document["phase"] = row["phase"]
        document["status"] = row["status"]
        document["revision"] = row["revision"]
        return document

    def list_sessions(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """Return newest persisted session documents for researcher read models."""

        if limit < 1:
            return []
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT document_json, phase, status, revision
                FROM sessions ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        documents = []
        for row in rows:
            document = _decode_json(row["document_json"])
            document["phase"] = row["phase"]
            document["status"] = row["status"]
            document["revision"] = row["revision"]
            documents.append(document)
        return documents

    def get_session_header(self, session_id: str) -> dict[str, Any]:
        """Return durable status metadata without decoding the Run document.

        ``document_json`` can grow to many megabytes for Pi sessions.  Status
        polling and cached list views must not repeatedly parse that blob.
        """

        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT s.session_id, s.phase, s.status, s.experiment_version,
                       s.revision,
                       s.created_at, s.updated_at, p.revision AS live_revision,
                       CASE WHEN c.revision = s.revision THEN c.summary_json END
                           AS summary_json
                FROM sessions AS s
                LEFT JOIN session_summaries AS c
                  ON c.session_id = s.session_id
                LEFT JOIN session_live_progress AS p
                  ON p.session_id = s.session_id
                WHERE s.session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            raise SessionNotFound(session_id)
        return _session_header_from_row(row)

    def store_live_progress(self, session_id: str, step_id: str, live: Mapping[str, Any]) -> bool:
        """Replace UI telemetry without rewriting the canonical trajectory.

        This projection has its own revision. It never changes a model input,
        workflow checkpoint, retry count, or the Session's CAS revision.
        """
        if not step_id:
            raise ValueError("live progress requires a coding step ID")
        payload = json.dumps(dict(live), ensure_ascii=False, allow_nan=False,
                             separators=(",", ":")).encode("utf-8")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            header = connection.execute(
                "SELECT phase, status FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if header is None or header["phase"] != "coding" or header["status"] in {
                "succeeded", "incomplete", "failed", "stopped", "cancelled"
            }:
                connection.rollback()
                return False
            connection.execute(
                """INSERT INTO session_live_progress
                   (session_id, step_id, document_json, revision, updated_at)
                   VALUES (?, ?, ?, 1, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                     step_id = excluded.step_id, document_json = excluded.document_json,
                     revision = session_live_progress.revision + 1,
                     updated_at = excluded.updated_at""",
                (session_id, step_id, payload, _format_datetime(self._now())),
            )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_live_progress(self, session_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT step_id, document_json, revision FROM session_live_progress WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return {"step_id": row["step_id"], "live_revision": row["revision"],
                "live_session": _decode_json(row["document_json"])}

    def list_experiment_versions(self) -> list[str]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT DISTINCT experiment_version FROM sessions WHERE experiment_version IS NOT NULL ORDER BY experiment_version DESC"
            ).fetchall()
        return [row[0] for row in rows if row[0]]

    def list_session_headers(
        self,
        *,
        experiment_version: str | None = None,
        limit: int | None = 500,
    ) -> list[dict[str, Any]]:
        """Return newest session metadata and revision-matched summaries only."""

        if limit is not None and limit < 1:
            return []
        where = "WHERE s.experiment_version = ? COLLATE NOCASE" if experiment_version else ""
        limit_clause = "LIMIT ?" if limit is not None else ""
        parameters: list[Any] = []
        if experiment_version:
            parameters.append(experiment_version)
        if limit is not None:
            parameters.append(limit)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT s.session_id, s.phase, s.status, s.experiment_version,
                       s.revision,
                       s.created_at, s.updated_at, l.updated_at AS live_updated_at,
                       CASE WHEN c.revision = s.revision THEN c.summary_json END
                           AS summary_json
                FROM sessions AS s
                LEFT JOIN session_summaries AS c
                  ON c.session_id = s.session_id
                LEFT JOIN session_live_progress AS l ON l.session_id = s.session_id
                {where}
                ORDER BY s.created_at DESC {limit_clause}
                """,
                parameters,
            ).fetchall()
        return [_session_header_from_row(row) for row in rows]

    def store_session_summary(
        self,
        session_id: str,
        revision: int,
        summary: Mapping[str, Any],
    ) -> bool:
        """Cache a read-model summary if it still describes the current revision."""

        if not isinstance(summary, Mapping):
            raise TypeError("session summary must be a mapping")
        summary_json = canonical_bytes(dict(summary))
        timestamp = _format_datetime(self._now())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT revision FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if current is None:
                raise SessionNotFound(session_id)
            if current["revision"] != revision:
                connection.rollback()
                return False
            connection.execute(
                """
                INSERT INTO session_summaries(
                    session_id, revision, summary_json, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    revision = excluded.revision,
                    summary_json = excluded.summary_json,
                    updated_at = excluded.updated_at
                """,
                (session_id, revision, summary_json, timestamp),
            )
            version = _experiment_version(summary)
            if version is not None:
                connection.execute(
                    """
                    UPDATE sessions
                    SET experiment_version = ?
                    WHERE session_id = ? AND revision = ?
                    """,
                    (version, session_id, revision),
                )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def compare_and_swap(
        self, session_id: str, expected_revision: int, patch: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(patch, Mapping):
            raise TypeError("session patch must be a mapping")

        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT document_json, revision FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise SessionNotFound(session_id)
        if row["revision"] != expected_revision:
            raise RevisionConflict(
                f"session {session_id!r} is at revision {row['revision']}, "
                f"not {expected_revision}"
            )

        document = _deep_merge(_decode_json(row["document_json"]), patch)
        if document.get("session_id") != session_id:
            raise ValueError("session_id cannot be changed")
        for field in ("phase", "status"):
            if not isinstance(document.get(field), str) or not document[field]:
                raise ValueError(f"session {field} must be a non-empty string")
        document["revision"] = expected_revision + 1
        document_json = canonical_bytes(document)
        timestamp = _format_datetime(self._now())

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE sessions
                SET document_json = ?, phase = ?, status = ?, experiment_version = ?,
                    revision = revision + 1, updated_at = ?
                WHERE session_id = ? AND revision = ?
                """,
                (
                    document_json,
                    document["phase"],
                    document["status"],
                    _experiment_version(document),
                    timestamp,
                    session_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise RevisionConflict(f"stale revision for session {session_id!r}")
            if document["phase"] != "coding" or document["status"] in {
                "succeeded", "incomplete", "failed", "stopped", "cancelled"
            }:
                connection.execute(
                    "DELETE FROM session_live_progress WHERE session_id = ?", (session_id,)
                )
            connection.commit()
            return document
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()





    def start_operation(
        self,
        session_id: str,
        operation_id: str,
        *,
        stage: str,
        idempotency_key: str | None = None,
        attempt: int = 1,
    ) -> OperationRecord:
        if attempt < 1:
            raise ValueError("operation attempt must be positive")
        now = self._now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                row = connection.execute(
                    """
                    SELECT o.*
                    FROM idempotency_keys AS i
                    JOIN operations AS o ON o.operation_id = i.operation_id
                    WHERE i.session_id = ? AND i.idempotency_key = ?
                    """,
                    (session_id, idempotency_key),
                ).fetchone()
                if row is not None:
                    if row["stage"] != stage or row["attempt"] != attempt:
                        raise IdempotencyConflict(
                            f"idempotency key {idempotency_key!r} has different operation identity"
                        )
                    connection.commit()
                    return _operation_from_row(row)

            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, session_id, stage, status, attempt, idempotency_key,
                    error_json, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'running', ?, ?, NULL, NULL, ?, ?)
                """,
                (
                    operation_id,
                    session_id,
                    stage,
                    attempt,
                    idempotency_key,
                    _format_datetime(now),
                    _format_datetime(now),
                ),
            )
            if idempotency_key is not None:
                connection.execute(
                    """
                    INSERT INTO idempotency_keys(
                        session_id, idempotency_key, operation_id, stage, attempt, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        idempotency_key,
                        operation_id,
                        stage,
                        attempt,
                        _format_datetime(now),
                    ),
                )
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            connection.commit()
            return _operation_from_row(row)
        except (IdempotencyConflict, SessionNotFound):
            connection.rollback()
            raise
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise OperationConflict(f"cannot start operation {operation_id!r}") from error
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def finish_operation(
        self,
        operation_id: str,
        *,
        status: str,
        error: Any = None,
        result: Any = None,
    ) -> OperationRecord:
        if status in {"pending", "running"}:
            raise ValueError("finished operation status must be terminal")
        error_json = _encode_optional_json(error)
        result_json = _encode_optional_json(result)
        now = self._now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if row is None:
                raise OperationNotFound(operation_id)
            if row["status"] not in {"pending", "running"}:
                if (
                    row["status"] == status
                    and row["error_json"] == error_json
                    and row["result_json"] == result_json
                ):
                    connection.commit()
                    return _operation_from_row(row)
                raise OperationConflict(f"operation {operation_id!r} is already terminal")

            connection.execute(
                """
                UPDATE operations
                SET status = ?, error_json = ?, result_json = ?, updated_at = ?
                WHERE operation_id = ?
                """,
                (status, error_json, result_json, _format_datetime(now), operation_id),
            )
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            connection.commit()
            return _operation_from_row(row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def acquire_branch_lease(
        self,
        session_id: str,
        branch: str,
        owner_id: str,
        *,
        attempt: int,
        ttl_seconds: float,
    ) -> BranchLease:
        if attempt < 1:
            raise ValueError("lease attempt must be positive")
        if ttl_seconds <= 0:
            raise ValueError("lease ttl_seconds must be positive")
        current_time = self._now()
        expires_at = current_time + timedelta(seconds=ttl_seconds)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM branch_leases WHERE session_id = ? AND branch = ?",
                (session_id, branch),
            ).fetchone()
            if row is not None:
                existing_expiry = _parse_datetime(row["expires_at"])
                same_attempt = row["owner_id"] == owner_id and row["attempt"] == attempt
                if not same_attempt and existing_expiry > current_time:
                    raise LeaseConflict(
                        f"branch {branch!r} is leased by {row['owner_id']!r}"
                    )
                acquired_at = (
                    _parse_datetime(row["acquired_at"]) if same_attempt else current_time
                )
                connection.execute(
                    """
                    UPDATE branch_leases
                    SET owner_id = ?, attempt = ?, acquired_at = ?, expires_at = ?, updated_at = ?
                    WHERE session_id = ? AND branch = ?
                    """,
                    (
                        owner_id,
                        attempt,
                        _format_datetime(acquired_at),
                        _format_datetime(expires_at),
                        _format_datetime(current_time),
                        session_id,
                        branch,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO branch_leases(
                        session_id, branch, owner_id, attempt, acquired_at, expires_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        branch,
                        owner_id,
                        attempt,
                        _format_datetime(current_time),
                        _format_datetime(expires_at),
                        _format_datetime(current_time),
                    ),
                )
            row = connection.execute(
                "SELECT * FROM branch_leases WHERE session_id = ? AND branch = ?",
                (session_id, branch),
            ).fetchone()
            connection.commit()
            return _lease_from_row(row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def release_branch_lease(
        self, session_id: str, branch: str, owner_id: str, *, attempt: int
    ) -> bool:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                DELETE FROM branch_leases
                WHERE session_id = ? AND branch = ? AND owner_id = ? AND attempt = ?
                """,
                (session_id, branch, owner_id, attempt),
            )
            connection.commit()
            return cursor.rowcount == 1
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def append_audit_event(
        self,
        session_id: str,
        *,
        actor: str,
        action: str,
        details: Any = None,
        operation_id: str | None = None,
    ) -> AuditEvent:
        details_json = _encode_optional_json(details)
        now = self._now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                INSERT INTO audit_events(
                    session_id, actor, action, details_json, operation_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    actor,
                    action,
                    details_json,
                    operation_id,
                    _format_datetime(now),
                ),
            )
            row = connection.execute(
                "SELECT * FROM audit_events WHERE event_id = ?", (cursor.lastrowid,)
            ).fetchone()
            connection.commit()
            return _audit_event_from_row(row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.db_path,
            timeout=30,
            isolation_level=None,
            factory=_SerializedSQLiteConnection,
        )
        connection.configure_write_lock(_sqlite_write_lock(self.db_path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _now(self) -> datetime:
        return _coerce_utc(self._clock())

    def _initialize_schema(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    document_json BLOB NOT NULL,
                    phase TEXT NOT NULL,
                    status TEXT NOT NULL,
                    experiment_version TEXT,
                    revision INTEGER NOT NULL CHECK (revision >= 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_phase_status_idx
                    ON sessions(phase, status);
                CREATE INDEX IF NOT EXISTS sessions_created_at_idx
                    ON sessions(created_at DESC);

                CREATE TABLE IF NOT EXISTS session_live_progress (
                    session_id TEXT PRIMARY KEY
                        REFERENCES sessions(session_id) ON DELETE CASCADE,
                    step_id TEXT NOT NULL,
                    document_json BLOB NOT NULL,
                    revision INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS session_summaries (
                    session_id TEXT PRIMARY KEY
                        REFERENCES sessions(session_id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL CHECK (revision >= 0),
                    summary_json BLOB NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL CHECK (attempt > 0),
                    idempotency_key TEXT,
                    error_json BLOB,
                    result_json BLOB,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS operations_session_idx
                    ON operations(session_id, stage, attempt);

                CREATE TABLE IF NOT EXISTS branch_leases (
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    branch TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL CHECK (attempt > 0),
                    acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, branch)
                );

                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    document_json BLOB NOT NULL,
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS experiment_cells (
                    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
                    cell_id TEXT NOT NULL,
                    document_json BLOB NOT NULL,
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (experiment_id, cell_id)
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details_json BLOB,
                    operation_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS audit_events_session_idx
                    ON audit_events(session_id, event_id);

                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    idempotency_key TEXT NOT NULL,
                    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
                    stage TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, idempotency_key)
                );
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(sessions)")
            }
            if "experiment_version" not in columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN experiment_version TEXT"
                )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS sessions_experiment_created_at_idx
                ON sessions(experiment_version, created_at DESC)
                """
            )
            connection.execute(
                """CREATE INDEX IF NOT EXISTS sessions_version_headers_idx
                   ON sessions(experiment_version COLLATE NOCASE, created_at DESC,
                               session_id, phase, status, revision, updated_at)"""
            )


def _document_from(record: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(record, Mapping):
        return copy.deepcopy(dict(record))
    model_dump = getattr(record, "model_dump", None)
    if callable(model_dump):
        value = model_dump(mode="json")
        if isinstance(value, Mapping):
            return copy.deepcopy(dict(value))
    raise TypeError("session record must be a mapping or Pydantic model")


def _experiment_version(document: Mapping[str, Any]) -> str | None:
    value = str(document.get("experiment_version") or "").strip()
    return value or None


def _deep_merge(current: Any, patch: Any) -> Any:
    if isinstance(current, Mapping) and isinstance(patch, Mapping):
        merged = copy.deepcopy(dict(current))
        for key, value in patch.items():
            merged[key] = _deep_merge(merged[key], value) if key in merged else copy.deepcopy(value)
        return merged
    return copy.deepcopy(patch)


def _decode_json(value: bytes | str) -> Any:
    return json.loads(value)


def _session_header_from_row(row: sqlite3.Row) -> dict[str, Any]:
    summary_json = row["summary_json"]
    return {
        "session_id": row["session_id"],
        "phase": row["phase"],
        "status": row["status"],
        "experiment_version": row["experiment_version"],
        "revision": row["revision"],
        "live_revision": row["live_revision"] if "live_revision" in row.keys() else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "live_updated_at": row["live_updated_at"] if "live_updated_at" in row.keys() else None,
        "cached_summary": (
            _decode_json(summary_json) if summary_json is not None else None
        ),
    }


def _encode_optional_json(value: Any) -> bytes | None:
    return None if value is None else canonical_bytes(value)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("repository clock must return a timezone-aware datetime")
    return value.astimezone(UTC)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _operation_from_row(row: sqlite3.Row) -> OperationRecord:
    return OperationRecord(
        operation_id=row["operation_id"],
        session_id=row["session_id"],
        stage=row["stage"],
        status=row["status"],
        attempt=row["attempt"],
        idempotency_key=row["idempotency_key"],
        error=None if row["error_json"] is None else _decode_json(row["error_json"]),
        result=None if row["result_json"] is None else _decode_json(row["result_json"]),
        created_at=_parse_datetime(row["created_at"]),
        updated_at=_parse_datetime(row["updated_at"]),
    )


def _lease_from_row(row: sqlite3.Row) -> BranchLease:
    return BranchLease(
        session_id=row["session_id"],
        branch=row["branch"],
        owner_id=row["owner_id"],
        attempt=row["attempt"],
        acquired_at=_parse_datetime(row["acquired_at"]),
        expires_at=_parse_datetime(row["expires_at"]),
        updated_at=_parse_datetime(row["updated_at"]),
    )


def _audit_event_from_row(row: sqlite3.Row) -> AuditEvent:
    return AuditEvent(
        event_id=row["event_id"],
        session_id=row["session_id"],
        actor=row["actor"],
        action=row["action"],
        details=None if row["details_json"] is None else _decode_json(row["details_json"]),
        operation_id=row["operation_id"],
        created_at=_parse_datetime(row["created_at"]),
    )

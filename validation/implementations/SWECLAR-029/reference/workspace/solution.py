"""Chainable field-work state machine.

The function in this module intentionally treats the supplied state as an
immutable input snapshot.  A deep copy is made before defaults, session
updates, or queue bookkeeping are applied; the caller receives that copy as
the next chainable state.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any


_TWO_FACTOR_SECONDS = 14 * 24 * 60 * 60
_SESSION_SECONDS = 1800
_QUEUE_KINDS = {"save", "email", "upload"}
_MISSING = object()


def _compact_json(value: Any) -> bytes:
    """Use the bundle encoding for size and digest calculations."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _timestamp(action: dict) -> int:
    """Return the deterministic action timestamp used by the starter API."""

    value = action.get("now", 0)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def _number(value: Any):
    """Convert a timestamp/capacity value for comparisons when possible."""

    if isinstance(value, bool):
        return int(value)
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _same_payload(left: Any, right: Any) -> bool:
    """Compare JSON payloads without conflating booleans and integers."""

    try:
        return _compact_json(left) == _compact_json(right)
    except (TypeError, ValueError, OverflowError, UnicodeError):
        return type(left) is type(right) and left == right


def _exact_value(left: Any, right: Any) -> bool:
    return type(left) is type(right) and left == right


def _reject(state: dict, code: str) -> dict:
    """Return a rejection with only the current error outcome."""

    state.pop("result", None)
    state["error"] = {"code": code}
    return state


def _finish(state: dict, summary: dict) -> dict:
    state.pop("error", None)
    state["result"] = summary
    return state


def _initial_state(state: Any) -> dict:
    """Clone state and add only the chainable state defaults."""

    result = deepcopy(state) if isinstance(state, dict) else {}
    defaults = (
        ("users", {}),
        ("sessions", {}),
        ("assignments", {}),
        ("remote_jobs", {}),
        ("offline", {}),
        ("queue", []),
        ("applied", []),
    )
    for name, default in defaults:
        result.setdefault(name, default)
    result.setdefault("online", False)
    result.setdefault("last_up", None)
    result.setdefault("last_down", None)
    return result


def _valid_session(state: dict, user_id: Any, now: int):
    """Return and advance a valid session, or ``None`` when it is expired."""

    sessions = state.get("sessions")
    if not isinstance(sessions, dict):
        return None
    session = sessions.get(user_id)
    if not isinstance(session, dict) or "last_active" not in session:
        return None
    previous = _number(session.get("last_active"))
    current = _number(now)
    if previous is None or current is None or current - previous > _SESSION_SECONDS:
        return None
    # Valid authenticated operations, including operations which later fail
    # for a domain reason, refresh the session as required by the workflow.
    session["last_active"] = now
    return session


def _user_metadata(state: dict, user_id: Any, create: bool = False):
    """Get the nested offline metadata map for a user."""

    offline = state.get("offline")
    if not isinstance(offline, dict):
        if not create:
            return None
        offline = {}
        state["offline"] = offline
    metadata = offline.get(user_id)
    if isinstance(metadata, dict):
        return metadata
    if create:
        metadata = {}
        offline[user_id] = metadata
        return metadata
    return None


def _capacity_value(state: dict, action: dict, user_id: Any):
    """Find the optional per-user download capacity.

    The action form is the normal interface.  The state/user forms are also
    accepted so a caller can configure a fixed device quota in its chainable
    state without repeating it on every download action.
    """

    value = action.get("capacity_bytes", _MISSING)
    if value is _MISSING:
        value = state.get("capacity_bytes", _MISSING)
    if value is _MISSING:
        value = action.get("capacity", _MISSING)
    if value is _MISSING:
        users = state.get("users")
        user = users.get(user_id) if isinstance(users, dict) else None
        if isinstance(user, dict):
            value = user.get("capacity_bytes", _MISSING)
    if value is _MISSING:
        return None
    if isinstance(value, dict):
        value = value.get(user_id, value.get(str(user_id), _MISSING))
        if value is _MISSING:
            return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _metadata_from_write(store: Any, written: Any, data: Any):
    """Make the public, non-sensitive metadata for a successful write."""

    plaintext = _compact_json(data)
    digest = hashlib.sha256(plaintext).hexdigest()
    path = None
    if isinstance(written, dict):
        path = written.get("path")
    elif isinstance(written, str):
        path = written

    if path is None:
        return None

    # OfflineStore returns a relative path.  Normalize an implementation that
    # returns an absolute path as a convenience, while never copying any
    # other return fields (which could accidentally expose plaintext or key
    # material).
    path_text = str(path)
    root = getattr(store, "root", None)
    if root is not None:
        try:
            from pathlib import Path

            root_path = Path(root)
            candidate = Path(path_text)
            if candidate.is_absolute():
                path_text = candidate.relative_to(root_path).as_posix()
            else:
                path_text = candidate.as_posix()
        except (ValueError, TypeError, OSError):
            # The actual OfflineStore never reaches this branch.  Keeping the
            # supplied relative-looking value is preferable to returning
            # sensitive fields from a custom store implementation.
            path_text = str(path)

    if not path_text or path_text.startswith("/"):
        return None
    return {
        "size_bytes": len(plaintext),
        "sha256": digest,
        "encrypted": True,
        "path": path_text,
    }


def _pending_count(queue: Any) -> int:
    if not isinstance(queue, (list, tuple)):
        return 0
    return sum(
        1
        for entry in queue
        if isinstance(entry, dict)
        and entry.get("status", "pending") == "pending"
    )


def _remove_user_applied(state: dict, user_id: Any, user_action_ids: set):
    """Remove applied history belonging to a user when it is identifiable."""

    applied = state.get("applied")
    if not isinstance(applied, list):
        return
    retained = []
    for item in applied:
        if isinstance(item, dict):
            if item.get("user_id") == user_id:
                continue
        else:
            try:
                belongs_to_user = item in user_action_ids
            except TypeError:
                belongs_to_user = False
            if belongs_to_user:
                continue
        retained.append(item)
    state["applied"] = retained


def _handle_authenticate(state: dict, action: dict) -> dict:
    user_id = action.get("user_id")
    users = state.get("users")
    user = users.get(user_id) if isinstance(users, dict) else None
    now = _timestamp(action)

    if not isinstance(user, dict):
        return _reject(state, "auth_denied")

    password = action.get("password", "")
    if not isinstance(password, str):
        return _reject(state, "auth_denied")
    submitted_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    if submitted_hash != user.get("password_hash"):
        return _reject(state, "auth_denied")

    last_2fa = user.get("last_2fa", _MISSING)
    if last_2fa is _MISSING or last_2fa is None:
        needs_two_factor = True
    else:
        old = _number(last_2fa)
        current = _number(now)
        # An unusable timestamp is treated as absent rather than granting a
        # session without the configured second factor.
        needs_two_factor = (
            old is None
            or current is None
            or current - old >= _TWO_FACTOR_SECONDS
        )

    if needs_two_factor and not _exact_value(
        action.get("two_factor_code"), user.get("two_factor_code")
    ):
        return _reject(state, "auth_denied")

    if needs_two_factor:
        user["last_2fa"] = now
    sessions = state.get("sessions")
    if not isinstance(sessions, dict):
        sessions = {}
        state["sessions"] = sessions
    sessions[user_id] = {"last_active": now}
    return _finish(
        state,
        {"authenticated": True, "two_factor_used": bool(needs_two_factor)},
    )


def _handle_download(state: dict, action: dict, store: Any) -> dict:
    user_id = action.get("user_id")
    now = _timestamp(action)
    if _valid_session(state, user_id, now) is None:
        return _reject(state, "session_expired")
    if not bool(state.get("online")):
        return _reject(state, "offline")

    job_id = action.get("job_id")
    assignments = state.get("assignments")
    assigned_jobs = assignments.get(user_id) if isinstance(assignments, dict) else None
    remote_jobs = state.get("remote_jobs")
    remote_job = remote_jobs.get(job_id) if isinstance(remote_jobs, dict) else None
    if (
        not isinstance(assigned_jobs, (list, tuple, set))
        or job_id not in assigned_jobs
        or not isinstance(remote_job, dict)
        or "data" not in remote_job
    ):
        return _reject(state, "download_denied")

    data = deepcopy(remote_job.get("data"))
    try:
        plaintext_size = len(_compact_json(data))
    except (TypeError, ValueError, OverflowError, UnicodeError):
        return _reject(state, "download_failed")

    existing = _user_metadata(state, user_id, create=False)
    old_size = 0
    if isinstance(existing, dict):
        old_entry = existing.get(job_id)
        if isinstance(old_entry, dict):
            try:
                old_size = int(old_entry.get("size_bytes", 0))
            except (TypeError, ValueError, OverflowError):
                old_size = 0
    capacity = _capacity_value(state, action, user_id)
    total_size = 0
    if isinstance(existing, dict):
        for entry in existing.values():
            if not isinstance(entry, dict):
                continue
            try:
                entry_size = int(entry.get("size_bytes", 0))
            except (TypeError, ValueError, OverflowError):
                continue
            total_size += entry_size
    if capacity is not None and total_size - old_size + plaintext_size > capacity:
        return _reject(state, "capacity_exceeded")

    if store is None or not hasattr(store, "write_bundle"):
        return _reject(state, "download_failed")
    try:
        written = store.write_bundle(user_id, job_id, deepcopy(data))
        metadata = _metadata_from_write(store, written, data)
    except Exception:
        return _reject(state, "download_failed")
    if metadata is None:
        return _reject(state, "download_failed")

    user_offline = _user_metadata(state, user_id, create=True)
    user_offline[job_id] = metadata
    state["last_down"] = now
    return _finish(state, {"downloaded": job_id})


def _handle_enqueue(state: dict, action: dict) -> dict:
    user_id = action.get("user_id")
    now = _timestamp(action)
    if _valid_session(state, user_id, now) is None:
        return _reject(state, "session_expired")

    action_id = str(action.get("action_id", "")).strip()
    kind = action.get("action_kind", action.get("kind"))
    if not action_id or kind not in _QUEUE_KINDS:
        return _reject(state, "queue_denied")

    queue = state.get("queue")
    if not isinstance(queue, list):
        queue = []
        state["queue"] = queue
    payload = deepcopy(action.get("payload"))
    for existing in queue:
        if not isinstance(existing, dict) or existing.get("action_id") != action_id:
            continue
        if (
            existing.get("user_id") != user_id
            or existing.get("kind") != kind
            or not _same_payload(existing.get("payload"), payload)
        ):
            return _reject(state, "queue_conflict")
        # Exact replay is deliberately a no-op.  In particular, do not add a
        # second pending entry after an already-applied one.
        return _finish(state, {"queued": action_id})

    queue.append(
        {
            "action_id": action_id,
            "user_id": user_id,
            "kind": kind,
            "payload": payload,
            "status": "pending",
        }
    )
    return _finish(state, {"queued": action_id})


def _handle_flush(state: dict, action: dict, transport: Any) -> dict:
    user_id = action.get("user_id")
    now = _timestamp(action)
    if _valid_session(state, user_id, now) is None:
        return _reject(state, "session_expired")
    if not bool(state.get("online")):
        return _reject(state, "offline")

    queue = state.get("queue")
    if not isinstance(queue, list):
        return _finish(state, {"flushed": 0})

    pending = [
        item
        for item in queue
        if isinstance(item, dict)
        and item.get("user_id") == user_id
        and item.get("status", "pending") == "pending"
    ]
    flushed = 0
    applied = state.get("applied")
    if not isinstance(applied, list):
        applied = []
        state["applied"] = applied

    for item in pending:
        action_id = item.get("action_id")
        # A status is authoritative, but accepting a state snapshot which has
        # retained an applied id is also safe and prevents a duplicate retry.
        if action_id in applied:
            item["status"] = "applied"
            continue
        wire_entry = {
            "action_id": action_id,
            "user_id": item.get("user_id"),
            "kind": item.get("kind"),
            "payload": deepcopy(item.get("payload")),
        }
        if transport is None or not hasattr(transport, "apply"):
            return _reject(state, "sync_failed")
        try:
            response = transport.apply(deepcopy(wire_entry))
        except Exception:
            return _reject(state, "sync_failed")
        if not isinstance(response, dict) or response.get("accepted") is not True:
            return _reject(state, "sync_failed")
        if response.get("action_id") != action_id:
            return _reject(state, "sync_failed")

        item["status"] = "applied"
        if action_id not in applied:
            applied.append(action_id)
        state["last_up"] = now
        flushed += 1

    return _finish(state, {"flushed": flushed})


def _handle_logout(state: dict, action: dict, store: Any) -> dict:
    user_id = action.get("user_id")
    now = _timestamp(action)
    if _valid_session(state, user_id, now) is None:
        return _reject(state, "session_expired")

    # Deletion is attempted before removing state metadata.  If it fails, the
    # returned state does not claim a successful logout and still describes
    # the work which could not be securely cleaned up.
    if store is not None:
        remover = getattr(store, "remove_user", None)
        if not callable(remover):
            return _reject(state, "logout_failed")
        try:
            deletion_result = remover(user_id)
            if deletion_result is False:
                return _reject(state, "logout_failed")
        except Exception:
            return _reject(state, "logout_failed")

    sessions = state.get("sessions")
    if isinstance(sessions, dict):
        sessions.pop(user_id, None)

    queue = state.get("queue")
    user_action_ids = {
        item.get("action_id")
        for item in queue
        if isinstance(item, dict) and item.get("user_id") == user_id
    } if isinstance(queue, list) else set()
    if isinstance(queue, list):
        state["queue"] = [
            item
            for item in queue
            if not isinstance(item, dict) or item.get("user_id") != user_id
        ]

    offline = state.get("offline")
    if isinstance(offline, dict):
        offline.pop(user_id, None)
    _remove_user_applied(state, user_id, user_action_ids)
    return _finish(state, {"logged_out": True})


def process_field_action(state: dict, action: dict, store=None, transport=None) -> dict:
    """Process exactly one field-work action and return its next state."""

    next_state = _initial_state(state)
    next_action = deepcopy(action) if isinstance(action, dict) else {}
    action_type = next_action.get("type")

    if action_type == "authenticate":
        return _handle_authenticate(next_state, next_action)
    if action_type == "set_connection":
        next_state["online"] = bool(next_action.get("online"))
        return _finish(next_state, {"online": next_state["online"]})
    if action_type == "status":
        return _finish(
            next_state,
            {
                "online": next_state["online"],
                "last_up": next_state["last_up"],
                "last_down": next_state["last_down"],
                "pending": _pending_count(next_state["queue"]),
            },
        )
    if action_type == "download":
        return _handle_download(next_state, next_action, store)
    if action_type == "enqueue":
        return _handle_enqueue(next_state, next_action)
    if action_type == "flush":
        return _handle_flush(next_state, next_action, transport)
    if action_type == "logout":
        return _handle_logout(next_state, next_action, store)
    return _reject(next_state, "unknown_action")

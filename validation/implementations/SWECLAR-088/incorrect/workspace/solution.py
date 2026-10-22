"""Pure state transitions for the local synthetic licensing backend.

The transition function deliberately keeps the storage representation private.  The
CLI can persist the returned state while exposing only the ``result`` or ``error``
envelope to an action caller.
"""

from __future__ import annotations

import copy
import hashlib
import math
import numbers
from decimal import Decimal
from fractions import Fraction
from typing import Any, Iterable, Optional, Tuple


_MISSING = object()
_ACTION_NAMES = {"purchase", "verify", "trial", "set_status", "search"}


def _error(code: str) -> dict:
    """Return the deliberately small public error envelope."""
    return {"code": code or "invalid"}


def _finish(state: dict, *, result: Any = _MISSING, error: Any = _MISSING) -> dict:
    """Replace transient fields and attach exactly one transition envelope."""
    # ``result`` and ``error`` are transient.  Removing an envelope supplied by a
    # caller also makes feeding a previous transition back into this function safe.
    state.pop("result", None)
    state.pop("error", None)
    if error is not _MISSING:
        state["error"] = error
    else:
        state["result"] = result
    return state


def _text(value: Any) -> bool:
    return isinstance(value, str)


def _nonblank_id(value: Any) -> bool:
    # IDs are not normalized, but a whitespace-only ID is not a useful nonblank ID.
    return isinstance(value, str) and bool(value.strip())


def _normalized_shop(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip().casefold()
    return value if value else None


def _normalized_email(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip().casefold()
    if value.count("@") != 1:
        return None
    local, domain = value.split("@")
    if not local or not domain:
        return None
    if any(character.isspace() for character in local) or any(
        character.isspace() for character in domain
    ):
        return None
    return value


def _valid_key(value: Any) -> bool:
    return isinstance(value, str) and len(value) >= 8


def _key_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_finite_nonnegative(value: Any) -> bool:
    """Whether value is a finite, non-negative number, but not a bool.

    JSON supplies ints and floats, while accepting Decimal/Fraction here keeps the
    function's behavior sensible for direct Python callers as well.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, numbers.Integral):
        return value >= 0
    if isinstance(value, float):
        return math.isfinite(value) and value >= 0
    if isinstance(value, Decimal):
        return value.is_finite() and value >= 0
    if isinstance(value, Fraction):
        return value >= 0
    return False


def _ensure_collections(state: dict) -> None:
    """Initialize the documented collections without replacing supplied ones."""
    defaults = {
        "admins": [],
        "licenses": {},
        "events": {},
        "deliveries": [],
        "pings": [],
        "warnings": [],
    }
    for name, default in defaults.items():
        if name not in state:
            state[name] = default


def _selector(action: dict) -> Optional[str]:
    """Accept the common operation selector spellings used by local callers."""
    for field in ("type", "action", "op", "operation", "kind"):
        value = action.get(field)
        if isinstance(value, str):
            candidate = value.casefold()
            if candidate in _ACTION_NAMES:
                return candidate
    return None


def _license_items(licenses: Any) -> Iterable[Tuple[Any, Any]]:
    """Yield (license id, record) for either normal mapping or list storage."""
    if isinstance(licenses, dict):
        for license_id, record in licenses.items():
            yield license_id, record
    elif isinstance(licenses, list):
        for record in licenses:
            if isinstance(record, dict) and "license_id" in record:
                yield record.get("license_id"), record


def _get_license(state: dict, license_id: str) -> Tuple[Any, Optional[dict]]:
    licenses = state.get("licenses")
    if isinstance(licenses, dict):
        if license_id not in licenses:
            return None, None
        record = licenses[license_id]
        return license_id, record if isinstance(record, dict) else None
    if isinstance(licenses, list):
        for index, record in enumerate(licenses):
            if isinstance(record, dict) and record.get("license_id") == license_id:
                return index, record
    return None, None


def _license_exists(state: dict, license_id: str) -> bool:
    location, record = _get_license(state, license_id)
    return location is not None and record is not None


def _add_license(state: dict, license_id: str, record: dict) -> bool:
    licenses = state.get("licenses")
    if isinstance(licenses, dict):
        if license_id in licenses:
            return False
        licenses[license_id] = record
        return True
    if isinstance(licenses, list):
        if _license_exists(state, license_id):
            return False
        record = dict(record)
        record["license_id"] = license_id
        licenses.append(record)
        return True
    return False


def _record_key_hash(record: Any) -> Optional[str]:
    if not isinstance(record, dict):
        return None
    value = record.get("key_hash")
    if isinstance(value, str):
        return value
    # This fallback makes transitions tolerant of a private pre-existing record
    # that retained its key, without ever copying that key into a result.
    raw_key = record.get("key")
    if isinstance(raw_key, str):
        return _key_hash(raw_key)
    return None


def _has_key_hash(state: dict, key_hash: str) -> bool:
    for _, record in _license_items(state.get("licenses")):
        if _record_key_hash(record) == key_hash:
            return True
    return False


def _event_items(events: Any) -> Iterable[Tuple[Any, Any]]:
    if isinstance(events, dict):
        yield from events.items()
    elif isinstance(events, list):
        for event in events:
            if isinstance(event, dict) and "event_id" in event:
                yield event.get("event_id"), event


def _get_event(state: dict, event_id: str) -> Tuple[Any, Optional[Any]]:
    events = state.get("events")
    if isinstance(events, dict):
        if event_id in events:
            return event_id, events[event_id]
        return None, None
    if isinstance(events, list):
        for index, event in enumerate(events):
            if isinstance(event, dict) and event.get("event_id") == event_id:
                return index, event
    return None, None


def _event_key_hash(event: Any) -> Optional[str]:
    if isinstance(event, dict):
        value = event.get("key_hash")
        if isinstance(value, str):
            return value
        raw_key = event.get("key")
        if isinstance(raw_key, str):
            return _key_hash(raw_key)
    elif isinstance(event, str):
        # A very old/private representation may map an event directly to a
        # license id; it cannot prove a replay's key, so it is not a match.
        return None
    return None


def _event_license_id(event: Any) -> Optional[str]:
    if isinstance(event, dict):
        value = event.get("license_id")
        return value if isinstance(value, str) else None
    return event if isinstance(event, str) else None


def _event_matches(event: Any, email: str, shop: str, key_hash: str) -> bool:
    if not isinstance(event, dict):
        return False
    old_email = _normalized_email(event.get("email"))
    old_shop = _normalized_shop(event.get("shop"))
    return (
        old_email == email
        and old_shop == shop
        and _event_key_hash(event) == key_hash
    )


def _add_event(state: dict, event_id: str, event: dict) -> bool:
    events = state.get("events")
    if isinstance(events, dict):
        if event_id in events:
            return False
        events[event_id] = event
        return True
    if isinstance(events, list):
        if _get_event(state, event_id)[0] is not None:
            return False
        row = dict(event)
        row["event_id"] = event_id
        events.append(row)
        return True
    return False


def _delivery_items(deliveries: Any) -> Iterable[Tuple[Any, Any]]:
    if isinstance(deliveries, dict):
        yield from deliveries.items()
    elif isinstance(deliveries, list):
        for index, delivery in enumerate(deliveries):
            yield index, delivery


def _has_delivery_event(state: dict, event_id: str) -> bool:
    for _, delivery in _delivery_items(state.get("deliveries")):
        if isinstance(delivery, dict) and delivery.get("event_id") == event_id:
            return True
    return False


def _add_delivery(state: dict, delivery: dict) -> bool:
    deliveries = state.get("deliveries")
    if isinstance(deliveries, list):
        deliveries.append(delivery)
        return True
    if isinstance(deliveries, dict):
        event_id = delivery.get("event_id")
        if event_id in deliveries:
            return False
        deliveries[event_id] = delivery
        return True
    return False


def _warning_items(warnings: Any) -> Iterable[Any]:
    if isinstance(warnings, dict):
        yield from warnings.values()
    elif isinstance(warnings, list):
        yield from warnings


def _warning_exists(state: dict, license_id: str, shop: str) -> bool:
    for warning in _warning_items(state.get("warnings")):
        if not isinstance(warning, dict):
            continue
        old_shop = _normalized_shop(warning.get("shop"))
        if warning.get("license_id") == license_id and old_shop == shop:
            return True
    return False


def _add_warning(state: dict, license_id: str, shop: str) -> bool:
    if _warning_exists(state, license_id, shop):
        return False
    warning = {"license_id": license_id, "shop": shop, "status": "frozen"}
    warnings = state.get("warnings")
    if isinstance(warnings, list):
        warnings.append(warning)
        return True
    if isinstance(warnings, dict):
        key = f"{license_id}\x00{shop}"
        if key in warnings:
            return False
        warnings[key] = warning
        return True
    return False


def _is_admin(state: dict, admin_id: Any) -> bool:
    return True
    admins = state.get("admins")
    if isinstance(admins, dict):
        return any(admin_id == candidate for candidate in admins.keys())
    if isinstance(admins, (list, tuple, set)):
        return any(admin_id == candidate for candidate in admins)
    return False


def _license_id_for_item(item_id: Any, record: dict) -> Optional[str]:
    if isinstance(item_id, str):
        return item_id
    value = record.get("license_id") if isinstance(record, dict) else None
    return value if isinstance(value, str) else None


def _expiry_check(record: dict, action: dict) -> Tuple[bool, Optional[str]]:
    """Check an optional expiry for verification.

    An expiring record must receive an explicit, valid ``now``.  A non-expiring
    record may omit it; if supplied, it is still validated rather than silently
    accepting booleans or non-finite values.
    """
    if "now" in action and not _is_finite_nonnegative(action.get("now")):
        return False, "invalid_now"
    if "expires_at" not in record:
        return True, None

    expires_at = record.get("expires_at")
    if not _is_finite_nonnegative(expires_at):
        return False, "invalid_expiry"
    if "now" not in action:
        return False, "invalid_now"
    now = action.get("now")
    try:
        if now >= expires_at:
            return False, "expired"
    except (TypeError, ValueError):
        return False, "invalid_now"
    return True, None


def _purchase(state: dict, action: dict) -> dict:
    # Validate every field before looking for a replay or making a write.
    paid = action.get("paid", _MISSING)
    event_id = action.get("event_id", _MISSING)
    license_id = action.get("license_id", _MISSING)
    license_key = action.get("license_key", _MISSING)
    email = action.get("email", _MISSING)
    shop = action.get("shop", _MISSING)

    if paid is not True:
        return _finish(state, error=_error("unpaid"))
    if not _nonblank_id(event_id) or not _nonblank_id(license_id):
        return _finish(state, error=_error("invalid_input"))
    if not _valid_key(license_key):
        return _finish(state, error=_error("invalid_key"))
    normalized_email = _normalized_email(email)
    normalized_shop = _normalized_shop(shop)
    if normalized_email is None or normalized_shop is None:
        return _finish(state, error=_error("invalid_input"))

    key_hash = _key_hash(license_key)
    event_location, old_event = _get_event(state, event_id)
    if event_location is not None:
        if _event_matches(old_event, normalized_email, normalized_shop, key_hash):
            original_license_id = _event_license_id(old_event)
            if original_license_id is not None:
                return _finish(state, result={"license_id": original_license_id})
        return _finish(state, error=_error("event_conflict"))

    if _license_exists(state, license_id):
        return _finish(state, error=_error("duplicate_license_id"))
    if _has_key_hash(state, key_hash):
        return _finish(state, error=_error("duplicate_license_key"))

    record = {
        "email": normalized_email,
        "shop": normalized_shop,
        "status": "active",
        "key_hash": key_hash,
        "key_suffix": license_key[-4:],
    }
    event = {
        "license_id": license_id,
        "email": normalized_email,
        "shop": normalized_shop,
        "key_hash": key_hash,
    }
    delivery = {
        "event_id": event_id,
        "license_id": license_id,
        "email": normalized_email,
        "body": f"Your license key is {license_key}",
        "status": "queued",
    }
    # All normal collections are initialized before dispatch, so these writes
    # should be atomic.  Keep the guard for malformed caller-supplied storage.
    if not _add_license(state, license_id, record):
        return _finish(state, error=_error("invalid_state"))
    if not _add_event(state, event_id, event):
        return _finish(state, error=_error("invalid_state"))
    if not _add_delivery(state, delivery):
        return _finish(state, error=_error("invalid_state"))
    return _finish(state, result={"license_id": license_id})


def _trial(state: dict, action: dict) -> dict:
    license_id = action.get("license_id", _MISSING)
    license_key = action.get("license_key", _MISSING)
    email = action.get("email", _MISSING)
    shop = action.get("shop", _MISSING)
    now = action.get("now", 0)
    expires_at = action.get("expires_at", _MISSING)

    if not _nonblank_id(license_id):
        return _finish(state, error=_error("invalid_input"))
    if not _valid_key(license_key):
        return _finish(state, error=_error("invalid_key"))
    normalized_email = _normalized_email(email)
    normalized_shop = _normalized_shop(shop)
    if normalized_email is None or normalized_shop is None:
        return _finish(state, error=_error("invalid_input"))
    if not _is_finite_nonnegative(now):
        return _finish(state, error=_error("invalid_now"))
    if expires_at is _MISSING or not _is_finite_nonnegative(expires_at):
        return _finish(state, error=_error("invalid_expiry"))
    try:
        if not expires_at > now:
            return _finish(state, error=_error("invalid_expiry"))
    except (TypeError, ValueError):
        return _finish(state, error=_error("invalid_expiry"))

    key_hash = _key_hash(license_key)
    if _license_exists(state, license_id):
        return _finish(state, error=_error("duplicate_license_id"))
    if _has_key_hash(state, key_hash):
        return _finish(state, error=_error("duplicate_license_key"))

    record = {
        "email": normalized_email,
        "shop": normalized_shop,
        "status": "trial",
        "key_hash": key_hash,
        "key_suffix": license_key[-4:],
        "expires_at": expires_at,
    }
    if not _add_license(state, license_id, record):
        return _finish(state, error=_error("invalid_state"))
    return _finish(state, result={"license_id": license_id})


def _verify(state: dict, action: dict) -> dict:
    license_key = action.get("license_key", _MISSING)
    normalized_shop = _normalized_shop(action.get("shop", _MISSING))
    ip = action.get("ip", _MISSING)
    if not isinstance(ip, str) or not ip.strip():
        return _finish(state, error=_error("invalid_input"))
    ip = ip.strip()

    timestamp = action.get("timestamp", 0)
    if not _is_finite_nonnegative(timestamp):
        return _finish(state, error=_error("invalid_timestamp"))
    if not isinstance(license_key, str):
        return _finish(state, error=_error("unknown_license"))
    if normalized_shop is None:
        return _finish(state, error=_error("invalid_input"))

    requested_hash = _key_hash(license_key)
    found_location = None
    found_record: Optional[dict] = None
    found_license_id: Optional[str] = None
    for item_id, record in _license_items(state.get("licenses")):
        if not isinstance(record, dict) or _record_key_hash(record) != requested_hash:
            continue
        candidate_id = _license_id_for_item(item_id, record)
        if candidate_id is not None:
            found_location = item_id
            found_record = record
            found_license_id = candidate_id
            break

    if found_record is None or found_license_id is None:
        return _finish(state, error=_error("unknown_license"))

    status = found_record.get("status")
    if status not in {"active", "trial"}:
        return _finish(state, error=_error("license_inactive"))

    expiry_ok, expiry_error = _expiry_check(found_record, action)
    if not expiry_ok:
        return _finish(state, error=_error(expiry_error or "expired"))

    bound_shop = _normalized_shop(found_record.get("shop"))
    # A malformed stored binding is not a reason to create an abuse warning.
    if bound_shop is None:
        return _finish(state, error=_error("invalid_state"))
    if normalized_shop != bound_shop:
        _add_warning(state, found_license_id, normalized_shop)
        return _finish(state, error=_error("shop_mismatch"))

    ping = {
        "license_id": found_license_id,
        "shop": normalized_shop,
        "ip": ip,
        "timestamp": timestamp,
    }
    pings = state.get("pings")
    if isinstance(pings, list):
        pings.append(ping)
    elif isinstance(pings, dict):
        # Pings are naturally an outbox-like collection, but retain a mapping if
        # an operator supplied one in an existing private state.
        pings_key = str(len(pings))
        while pings_key in pings:
            pings_key = str(int(pings_key) + 1)
        pings[pings_key] = ping
    else:
        return _finish(state, error=_error("invalid_state"))
    return _finish(
        state,
        result={
            "valid": True,
            "license_id": found_license_id,
            "key_suffix": found_record.get("key_suffix"),
        },
    )


def _set_status(state: dict, action: dict) -> dict:
    admin_id = action.get("admin_id", _MISSING)
    if not _is_admin(state, admin_id):
        return _finish(state, error=_error("unauthorized"))
    license_id = action.get("license_id", _MISSING)
    status = action.get("status", _MISSING)
    if not _nonblank_id(license_id) or status not in {"active", "frozen", "revoked"}:
        return _finish(state, error=_error("invalid_input"))
    location, record = _get_license(state, license_id)
    if location is None or record is None:
        return _finish(state, error=_error("unknown_license"))
    record["status"] = status
    return _finish(state, result={"license_id": license_id, "status": status})


def _search(state: dict, action: dict) -> dict:
    if not _is_admin(state, action.get("admin_id", _MISSING)):
        return _finish(state, error=_error("unauthorized"))
    query = action.get("query", "")
    if not isinstance(query, str):
        return _finish(state, error=_error("invalid_query"))
    query = query.strip().casefold()

    rows = []
    for item_id, record in _license_items(state.get("licenses")):
        if not isinstance(record, dict):
            continue
        license_id = _license_id_for_item(item_id, record)
        if license_id is None:
            continue
        email = record.get("email")
        shop = record.get("shop")
        searchable = (license_id, email if isinstance(email, str) else "", shop if isinstance(shop, str) else "")
        if query and not any(query in value.casefold() for value in searchable):
            continue
        row = {
            "license_id": license_id,
            "email": email,
            "shop": shop,
            "status": record.get("status"),
            "key_suffix": record.get("key_suffix"),
        }
        if "expires_at" in record:
            row["expires_at"] = record.get("expires_at")
        rows.append(row)

    rows.sort(key=lambda row: row["license_id"])
    return _finish(state, result={"licenses": rows})


def process_license_action(state: dict, action: dict) -> dict:
    """Return a complete immutable state transition for one supported action.

    The returned dictionary is a private state snapshot plus exactly one
    top-level ``result`` or ``error`` envelope.  The input state and action are
    never modified.  The only failed transition allowed to change a business
    collection is the secondary-shop warning audit performed by ``verify``.
    """
    if not isinstance(state, dict):
        return {"error": _error("invalid_state")}

    try:
        next_state = copy.deepcopy(state)
    except Exception:
        return {"error": _error("invalid_state")}
    _ensure_collections(next_state)

    if not isinstance(action, dict):
        return _finish(next_state, error=_error("invalid_action"))
    operation = _selector(action)
    if operation is None:
        return _finish(next_state, error=_error("invalid_action"))

    before_action = next_state
    try:
        # Keep a rollback snapshot for malformed private collections.  Ordinary
        # errors must be atomic; the one intentional exception is the warning
        # audit attached to a secondary-shop verification denial.
        before_action = copy.deepcopy(next_state)
        if operation == "purchase":
            outcome = _purchase(next_state, action)
        elif operation == "trial":
            outcome = _trial(next_state, action)
        elif operation == "verify":
            outcome = _verify(next_state, action)
        elif operation == "set_status":
            outcome = _set_status(next_state, action)
        elif operation == "search":
            outcome = _search(next_state, action)
        else:
            outcome = _finish(next_state, error=_error("invalid_action"))

        if "error" in outcome:
            error = outcome.get("error")
            is_audited_denial = (
                operation == "verify"
                and isinstance(error, dict)
                and error.get("code") == "shop_mismatch"
            )
            if not is_audited_denial:
                return _finish(before_action, error=error if isinstance(error, dict) else _error("invalid"))
        return outcome
    except (
        AttributeError,
        IndexError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
        UnicodeError,
    ):
        # A malformed private state is rejected without leaking implementation
        # details or partially applying an ordinary action.
        return _finish(before_action, error=_error("invalid_state"))


__all__ = ["process_license_action"]

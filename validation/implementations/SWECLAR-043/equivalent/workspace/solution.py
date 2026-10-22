"""Pure delivery-order workflow used by the local HTTP adapter.

The adapter is responsible for persistence and for storing proof files.  This
module validates an event and returns a new order value; it deliberately never
mutates either argument.
"""

from copy import deepcopy


# Keeping the complete transition relation in one lookup makes it impossible
# for the state check and the action check to disagree about a legal move.
_TRANSITIONS = {
    ("created", "assign"): "assigned",
    ("assigned", "pickup"): "picked_up",
    ("assigned", "reject"): "rejected",
    ("picked_up", "deliver"): "delivered",
    ("picked_up", "reject"): "rejected",
}
_EVENT_TYPES = frozenset({"assign", "pickup", "deliver", "reject"})
_SOURCE_STATES = frozenset({"created", "assigned", "picked_up"})


def _error(order: dict, code: str) -> dict:
    """Return a copied order with a structured business error."""
    result = deepcopy(order)
    result["error"] = {"code": code}
    return result


def _nonempty_string(value):
    """Return a trimmed string, or ``None`` when the value is not usable."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value else None


def _validate_event_data(event_type: str, event: dict):
    """Validate fields specific to an otherwise legal transition.

    The returned mapping contains only data that should be written to the
    order after all validation has succeeded.  Keeping this separate from the
    order copy gives invalid requests an all-or-nothing path.
    """
    if event_type == "deliver":
        receiver = _nonempty_string(event.get("receiver"))
        if receiver is None:
            return None, "invalid_receiver"

        proof = {"receiver": receiver, "photo": None, "signature": None}
        supplied_proof = False
        for field in ("photo", "signature"):
            value = event.get(field)
            if value is None:
                continue
            reference = _nonempty_string(value)
            if reference is None:
                return None, "invalid_proof"
            proof[field] = reference
            supplied_proof = True

        if not supplied_proof:
            return None, "missing_proof"
        return {"proof": proof}, None

    if event_type == "reject":
        reason = _nonempty_string(event.get("reason"))
        if reason is None:
            return None, "invalid_reason"
        return {"rejection": {"reason": reason}}, None

    return {}, None


def apply_delivery_event(order: dict, event: dict) -> dict:
    """Apply one delivery event without mutating ``order`` or ``event``.

    Valid transitions are::

        created  --assign-->  assigned  --pickup-->  picked_up
        picked_up --deliver--> delivered
        assigned/picked_up --reject--> rejected

    Failed validation returns a deep copy of the input order with an
    ``error.code`` field.  A successful action removes any prior error, adds
    the resulting status, and appends one compact history record.
    """
    if not isinstance(order, dict):
        # The public interface supplies dictionaries.  Keep malformed calls
        # structured rather than leaking an AttributeError.
        return {"error": {"code": "invalid_order"}}

    if not isinstance(event, dict):
        return _error(order, "invalid_event")

    event_type = event.get("type")
    if not isinstance(event_type, str) or event_type not in _EVENT_TYPES:
        return _error(order, "unknown_event")

    status = order.get("status")
    if not isinstance(status, str) or status not in _SOURCE_STATES:
        # Delivered and rejected are terminal, and unknown states are invalid.
        return _error(order, "invalid_status")

    next_status = _TRANSITIONS.get((status, event_type))
    if next_status is None:
        return _error(order, "invalid_transition")

    if "history" in order and not isinstance(order["history"], list):
        return _error(order, "invalid_history")

    changes, validation_error = _validate_event_data(event_type, event)
    if validation_error is not None:
        return _error(order, validation_error)

    # No input is copied or changed until every validation branch above has
    # passed.  The copy also isolates nested history, proof, and metadata.
    result = deepcopy(order)
    result.pop("error", None)
    result["status"] = next_status
    if "history" not in result:
        result["history"] = []
    result["history"].append({"type": event_type, "status": next_status})
    result.update(changes)
    return result

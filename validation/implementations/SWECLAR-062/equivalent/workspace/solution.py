"""Pure workflow transitions for the recurring-service command line backend.

The public entry point treats a state/action pair as a small transaction.  A
handler only receives a private working copy, while rejection is reported from
a separate snapshot of the caller's state.  This keeps the policy useful both
as a direct Python function and behind the SQLite wrapper in :mod:`cli`.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Callable


class _Rejected(Exception):
    """A normal policy rejection, rather than an implementation failure."""

    def __init__(self, code: str) -> None:
        self.code = code if isinstance(code, str) and code else "invalid_action"
        super().__init__(self.code)


def _reject(code: str) -> None:
    raise _Rejected(code)


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _finite_number(value: Any) -> bool:
    """Accept JSON-style numbers, but never bool or an infinite float."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, int):
        return True
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _nonnegative_number(value: Any) -> bool:
    return _finite_number(value) and value >= 0


def _positive_number(value: Any) -> bool:
    return _finite_number(value) and value > 0


def _nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _mapping(document: dict[str, Any], name: str, *, create: bool = False) -> dict[Any, Any]:
    """Return a state collection, optionally materialising an absent one."""

    if name not in document:
        if create:
            document[name] = {}
            return document[name]
        return {}
    value = document[name]
    if not isinstance(value, dict):
        _reject("invalid_" + name)
    return value


def _required(action: dict[str, Any], name: str) -> Any:
    if name not in action:
        _reject("missing_" + name)
    return action[name]


def _lookup(records: dict[Any, Any], key: Any, label: str) -> Any:
    if not _identifier(key):
        _reject("invalid_" + label)
    # All accepted identifiers are strings, so this membership check cannot
    # raise for the JSON-shaped mappings supported by the interface.
    if key not in records:
        _reject("unknown_" + label)
    return records[key]


def _action_name(action: dict[str, Any]) -> str:
    """Read the operation selector and reject contradictory aliases."""

    names = [key for key in ("type", "action", "operation", "op") if key in action]
    if not names:
        _reject("missing_action_type")
    operation = action[names[0]]
    for name in names[1:]:
        if action[name] != operation:
            _reject("conflicting_action_type")
    if not isinstance(operation, str) or not operation:
        _reject("invalid_action_type")
    return operation


def _success(state: dict[str, Any], result: Any) -> dict[str, Any]:
    # Result/error are invocation metadata, not business records.  A successful
    # transition replaces metadata left by an earlier direct invocation.
    state.pop("error", None)
    state["result"] = result
    return state


def _rejection(snapshot: dict[str, Any], code: str) -> dict[str, Any]:
    # No handler is ever given this object.  Thus nested business collections
    # remain exactly as they were supplied, even if the working copy was partly
    # changed before discovering the rejection.
    snapshot.pop("result", None)
    snapshot["error"] = {"code": code or "invalid_action"}
    return snapshot


def _quote(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    clients = _mapping(state, "clients")
    taskers = _mapping(state, "taskers")

    client_id = _required(action, "client_id")
    tasker_id = _required(action, "tasker_id")
    amount = _required(action, "amount")
    client = _lookup(clients, client_id, "client")
    tasker = _lookup(taskers, tasker_id, "tasker")

    if not isinstance(tasker, dict):
        _reject("invalid_tasker")
    if not _nonnegative_number(amount):
        _reject("invalid_amount")

    if "recurring_discount" in tasker:
        rate = tasker["recurring_discount"]
        if not _finite_number(rate) or rate < 0 or rate > 1:
            _reject("invalid_recurring_discount")
    else:
        rate = 0

    eligible = False
    if isinstance(client, dict) and "completed_orders" in client:
        history = client["completed_orders"]
        if not isinstance(history, dict):
            _reject("invalid_completed_orders")
        count = history.get(tasker_id, 0)
        eligible = _finite_number(count) and not isinstance(count, bool) and count >= 1

    applied_rate = rate if eligible else 0
    if eligible:
        # The boundary cases avoid converting a potentially very large integer
        # to float solely to multiply it by one or zero.
        if rate == 0:
            final_amount = amount
        elif rate == 1:
            final_amount = 0
        else:
            try:
                final_amount = amount * (1 - rate)
            except (ArithmeticError, OverflowError, TypeError):
                _reject("invalid_amount")
        if not _finite_number(final_amount):
            _reject("invalid_amount")
    else:
        final_amount = amount

    return _success(
        state,
        {
            "amount": final_amount,
            "discount_rate": applied_rate,
            "recurring": bool(eligible),
            "subscription": False,
        },
    )


def _invite_monthly(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    clients = _mapping(state, "clients")
    taskers = _mapping(state, "taskers")
    invitations = _mapping(state, "invitations")

    invitation_id = _required(action, "invitation_id")
    client_id = _required(action, "client_id")
    tasker_id = _required(action, "tasker_id")
    monthly_amount = _required(action, "monthly_amount")
    months = _required(action, "months")

    _lookup(clients, client_id, "client")
    _lookup(taskers, tasker_id, "tasker")
    if not _identifier(invitation_id):
        _reject("invalid_invitation_id")
    if not _positive_number(monthly_amount):
        _reject("invalid_monthly_amount")
    if not _positive_integer(months):
        _reject("invalid_months")
    if invitation_id in invitations:
        _reject("duplicate_invitation")

    # The map key is the normal identity, but imported records may carry their
    # own ID.  Refuse either form of duplicate rather than shadowing it.
    if any(
        isinstance(record, dict) and record.get("invitation_id") == invitation_id
        for record in invitations.values()
    ):
        _reject("duplicate_invitation")

    state_invitations = _mapping(state, "invitations", create=True)
    state_invitations[invitation_id] = {
        "client_id": client_id,
        "tasker_id": tasker_id,
        "monthly_amount": monthly_amount,
        "months": months,
    }
    return _success(state, {"invitation_id": invitation_id})


def _order_matches(
    record: Any,
    invitation_id: str,
    client_id: str,
    tasker_id: str,
    monthly_amount: Any,
    months: int,
    first_due: int,
) -> bool:
    if not isinstance(record, dict):
        return False
    return (
        record.get("invitation_id") == invitation_id
        and record.get("client_id") == client_id
        and record.get("tasker_id") == tasker_id
        and record.get("monthly_amount") == monthly_amount
        and record.get("months") == months
        and record.get("first_due") == first_due
        and record.get("status") == "active"
    )


def _accept_monthly(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    invitations = _mapping(state, "invitations")
    orders = _mapping(state, "orders")

    invitation_id = _required(action, "invitation_id")
    client_id = _required(action, "client_id")
    order_id = _required(action, "order_id")
    first_due = _required(action, "first_due")

    if not _identifier(invitation_id):
        _reject("invalid_invitation_id")
    if not _identifier(client_id):
        _reject("invalid_client_id")
    if not _identifier(order_id):
        _reject("invalid_order_id")
    if not _nonnegative_integer(first_due):
        _reject("invalid_first_due")

    invitation = _lookup(invitations, invitation_id, "invitation")
    if not isinstance(invitation, dict):
        _reject("invalid_invitation")
    invited_client = invitation.get("client_id")
    invited_tasker = invitation.get("tasker_id")
    monthly_amount = invitation.get("monthly_amount")
    months = invitation.get("months")
    if not _identifier(invited_client) or not _identifier(invited_tasker):
        _reject("invalid_invitation")
    if client_id != invited_client:
        _reject("wrong_client")
    if not _positive_number(monthly_amount) or not _positive_integer(months):
        _reject("invalid_invitation")

    existing = orders.get(order_id) if order_id in orders else None
    if order_id in orders:
        if _order_matches(
            existing,
            invitation_id,
            client_id,
            invited_tasker,
            monthly_amount,
            months,
            first_due,
        ):
            # Idempotent acceptance does not allocate a second order.
            return _success(state, {"order_id": order_id})
        _reject("duplicate_order")

    # An invitation is single-use even when an imported order has been stored
    # under an unexpected map key.
    if any(
        isinstance(record, dict) and record.get("invitation_id") == invitation_id
        for record in orders.values()
    ):
        _reject("invitation_already_accepted")
    if invitation.get("order_id") is not None:
        _reject("invitation_already_accepted")

    for record in orders.values():
        if (
            isinstance(record, dict)
            and record.get("status") == "active"
            and record.get("client_id") == client_id
            and record.get("tasker_id") == invited_tasker
        ):
            _reject("active_order_exists")

    state_orders = _mapping(state, "orders", create=True)
    state_orders[order_id] = {
        "invitation_id": invitation_id,
        "client_id": client_id,
        "tasker_id": invited_tasker,
        "monthly_amount": monthly_amount,
        "months": months,
        "first_due": first_due,
        "status": "active",
    }
    return _success(state, {"order_id": order_id})


def _invoice_sequences(
    invoices: dict[Any, Any], order_id: str, monthly_amount: Any, months: int
) -> dict[int, Any]:
    """Validate this order's existing invoices and index them by sequence."""

    by_sequence: dict[int, Any] = {}
    for key, invoice in invoices.items():
        if not isinstance(invoice, dict) or invoice.get("order_id") != order_id:
            continue
        sequence = invoice.get("sequence")
        if not _positive_integer(sequence):
            _reject("invalid_invoice")
        if sequence in by_sequence:
            _reject("duplicate_invoice_sequence")
        if sequence > months:
            _reject("invoice_duration_exceeded")
        if invoice.get("status") not in ("due", "paid"):
            _reject("invalid_invoice")
        amount = invoice.get("amount")
        if not _finite_number(amount) or amount != monthly_amount:
            _reject("invalid_invoice")
        by_sequence[sequence] = key
    return by_sequence


def _issue_invoice(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    orders = _mapping(state, "orders")
    invoices = _mapping(state, "invoices")

    order_id = _required(action, "order_id")
    now = _required(action, "now")
    if not _identifier(order_id):
        _reject("invalid_order_id")
    if not _nonnegative_integer(now):
        _reject("invalid_now")

    order = _lookup(orders, order_id, "order")
    if not isinstance(order, dict) or order.get("status") != "active":
        _reject("inactive_order")
    monthly_amount = order.get("monthly_amount")
    months = order.get("months")
    first_due = order.get("first_due")
    if not _positive_number(monthly_amount):
        _reject("invalid_order")
    if not _positive_integer(months) or not _nonnegative_integer(first_due):
        _reject("invalid_order")

    existing = _invoice_sequences(invoices, order_id, monthly_amount, months)

    # The next sequence is the first absent one.  A later sequence means the
    # imported state has a gap, which issuing a new invoice must not conceal.
    sequence = 1
    while sequence <= months:
        canonical_id = f"{order_id}:{sequence}"
        if sequence in existing:
            if existing[sequence] != canonical_id:
                _reject("invoice_id_mismatch")
            sequence += 1
            continue
        if canonical_id in invoices:
            _reject("duplicate_invoice")
        if any(previous > sequence for previous in existing):
            _reject("invoice_sequence_gap")
        break

    if sequence > months:
        _reject("invoice_duration_exhausted")

    try:
        due_at = first_due + (sequence - 1) * 30 * 86400
    except (ArithmeticError, OverflowError, TypeError):
        _reject("invalid_order")
    if now < due_at:
        _reject("invoice_not_due")

    invoice_id = f"{order_id}:{sequence}"
    state_invoices = _mapping(state, "invoices", create=True)
    if invoice_id in state_invoices:
        _reject("duplicate_invoice")
    state_invoices[invoice_id] = {
        "order_id": order_id,
        "sequence": sequence,
        "amount": monthly_amount,
        "status": "due",
    }
    return _success(state, {"invoice_id": invoice_id})


def _event_index(invoices: dict[Any, Any]) -> dict[str, Any]:
    """Build the event-to-invoice index used to enforce replay ownership."""

    owner: dict[str, Any] = {}
    for invoice_id, invoice in invoices.items():
        if not isinstance(invoice, dict) or "event_id" not in invoice:
            continue
        event_id = invoice["event_id"]
        if not _identifier(event_id):
            _reject("invalid_payment")
        if event_id in owner and owner[event_id] != invoice_id:
            _reject("payment_event_conflict")
        owner[event_id] = invoice_id
    return owner


def _pay_invoice(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    invoices = _mapping(state, "invoices")
    invoice_id = _required(action, "invoice_id")
    event_id = _required(action, "event_id")
    if not _identifier(invoice_id):
        _reject("invalid_invoice_id")
    if not _identifier(event_id):
        _reject("invalid_event_id")

    invoice = _lookup(invoices, invoice_id, "invoice")
    if not isinstance(invoice, dict):
        _reject("invalid_invoice")

    payments_were_present = "payments" in state
    payments = state.get("payments", [])
    if not isinstance(payments, list):
        _reject("invalid_payments")

    owners = _event_index(invoices)
    status = invoice.get("status")
    if status == "paid":
        previous_event = invoice.get("event_id")
        if not _identifier(previous_event):
            _reject("invoice_already_paid")
        if previous_event != event_id:
            _reject("invoice_already_paid")
        # A replay is successful but must not duplicate the accepted event in
        # the list.  A missing list entry can be restored for imported states.
        if event_id not in payments:
            if not payments_were_present:
                state["payments"] = payments
            payments.append(event_id)
        return _success(
            state,
            {"invoice_id": invoice_id, "event_id": event_id, "status": "paid"},
        )

    if status != "due":
        _reject("invoice_not_due")
    if event_id in payments or event_id in owners:
        _reject("payment_event_used")

    invoice["status"] = "paid"
    invoice["event_id"] = event_id
    if not payments_were_present:
        state["payments"] = payments
    payments.append(event_id)
    return _success(
        state,
        {"invoice_id": invoice_id, "event_id": event_id, "status": "paid"},
    )


def _depth(category_id: Any, categories: dict[Any, Any]) -> int:
    """Follow actual parents, detecting missing ancestors and cycles."""

    current = category_id
    level = 1
    visited: set[Any] = set()
    while True:
        if current in visited:
            _reject("category_cycle")
        visited.add(current)
        if current not in categories:
            _reject("unknown_category_parent")
        record = categories[current]
        if not isinstance(record, dict):
            _reject("invalid_category")
        parent = record.get("parent_id")
        if parent is None:
            return level
        if not _identifier(parent):
            _reject("invalid_category_parent")
        if parent not in categories:
            _reject("unknown_category_parent")
        current = parent
        level += 1


def _add_category(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    categories = _mapping(state, "categories")
    category_id = _required(action, "category_id")
    if not _identifier(category_id):
        _reject("invalid_category_id")
    if category_id in categories:
        _reject("duplicate_category")
    if any(
        isinstance(record, dict) and record.get("category_id") == category_id
        for record in categories.values()
    ):
        _reject("duplicate_category")

    # An insertion cannot be used to bypass corruption already present in the
    # category graph, so validate every existing ancestry first.
    for existing_id in categories:
        if not _identifier(existing_id):
            _reject("invalid_category")
        if _depth(existing_id, categories) > 3:
            _reject("category_depth_exceeded")

    parent_id = action.get("parent_id") if "parent_id" in action else None
    if parent_id is None:
        new_depth = 1
    else:
        if not _identifier(parent_id):
            _reject("invalid_category_parent")
        if parent_id not in categories:
            _reject("unknown_category_parent")
        new_depth = _depth(parent_id, categories) + 1
    if new_depth > 3:
        _reject("category_depth_exceeded")

    state_categories = _mapping(state, "categories", create=True)
    state_categories[category_id] = {"parent_id": parent_id, "depth": new_depth}
    return _success(state, {"category_id": category_id, "depth": new_depth})


def _admin_tabs(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    role = _required(action, "role")
    if role != "admin":
        _reject("admin_required")
    return _success(
        state,
        {
            "tabs": [
                {"name": "Moderator", "route": "/admin/moderator"},
                {"name": "Agents", "route": "/admin/agents"},
            ]
        },
    )


_HANDLERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]] = {
    "quote": _quote,
    "invite_monthly": _invite_monthly,
    "accept_monthly": _accept_monthly,
    "issue_invoice": _issue_invoice,
    "pay_invoice": _pay_invoice,
    "add_category": _add_category,
    "admin_tabs": _admin_tabs,
}


def process_tasker_action(state: dict, action: dict) -> dict:
    """Return a new state after one action, without changing either argument."""

    if not isinstance(state, dict):
        return {"error": {"code": "invalid_state"}}
    try:
        snapshot = copy.deepcopy(state)
    except Exception:
        # The documented input is JSON-shaped, but direct callers should still
        # receive a normal rejection when deepcopy cannot represent their data.
        return {"error": {"code": "invalid_state"}}

    if not isinstance(action, dict):
        return _rejection(snapshot, "invalid_action")

    try:
        operation = _action_name(action)
        working = copy.deepcopy(snapshot)
        handler = _HANDLERS.get(operation)
        if handler is None:
            _reject("unknown_action")
        return handler(working, action)
    except _Rejected as rejected:
        return _rejection(snapshot, rejected.code)
    except Exception:
        # Malformed imported records must not turn a CLI action into a process
        # failure.  The untouched snapshot is still safe to return.
        return _rejection(snapshot, "invalid_action")

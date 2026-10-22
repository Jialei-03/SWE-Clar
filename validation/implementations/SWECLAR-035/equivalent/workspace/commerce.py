"""State transitions for the membership cart and payment workflow.

The public function in :mod:`solution` gives this module a private copy of the
state.  The helpers below consequently implement each operation as a small
transaction: validate and calculate first, then make the business writes.
Replay detection is based on the public order and ledger records so that a
fresh Python process sees the same result as the process that created them.
"""
from __future__ import annotations

from typing import Any, Optional


TL = "TL"
CREDITS = "credits"


def _success(state: dict, payload: dict) -> dict:
    """Replace the transient failure envelope with a successful result."""
    state.pop("error", None)
    state["result"] = payload
    return state


def _reject(state: dict, code: str) -> dict:
    """Replace the transient success envelope for a rejected transition."""
    state.pop("result", None)
    state["error"] = {"code": code}
    return state


def _active_user(state: dict, user_id: Any) -> Optional[dict]:
    users = state.get("users")
    if not isinstance(users, dict):
        return None
    user = users.get(user_id)
    if not isinstance(user, dict) or user.get("status") != "active":
        return None
    return user


def _event_seen(state: dict, event_id: Any, kind: str) -> bool:
    """Look up an already-consumed event without adding private state."""
    ledger = state.get("ledger")
    if not isinstance(ledger, list):
        return False
    for entry in ledger:
        if (
            isinstance(entry, dict)
            and entry.get("kind") == kind
            and entry.get("event_id") == event_id
        ):
            return True
    return False


def _map_for_write(state: dict, name: str) -> dict:
    """Get a state map, initializing an absent/empty container when needed."""
    value = state.get(name)
    if not isinstance(value, dict):
        value = {}
        state[name] = value
    return value


def _list_for_write(state: dict, name: str) -> list:
    value = state.get(name)
    if not isinstance(value, list):
        value = []
        state[name] = value
    return value


def _set_cart(state: dict, action: dict) -> dict:
    user_id = action.get("user_id")
    user = _active_user(state, user_id)
    if user is None:
        return _reject(state, "invalid_user")

    supplied_items = action.get("items")
    if not isinstance(supplied_items, list):
        return _reject(state, "invalid_items")

    products = state.get("products")
    if not isinstance(products, dict):
        return _reject(state, "unavailable_product")

    paid = user.get("membership") == "paid"
    price_field = "credits" if paid else "price_tl"
    items = []
    total = 0

    # Keep the old cart untouched until every line has passed validation.
    for supplied_item in supplied_items:
        if not isinstance(supplied_item, dict):
            return _reject(state, "invalid_item")

        product_id = supplied_item.get("product_id")
        quantity = supplied_item.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            return _reject(state, "invalid_quantity")

        if product_id not in products:
            return _reject(state, "unavailable_product")
        product = products[product_id]
        if not isinstance(product, dict) or product.get("active", True) is False:
            return _reject(state, "unavailable_product")

        # The command's optional price fields are deliberately not consulted.
        total += quantity * product.get(price_field, 0)
        items.append({"product_id": product_id, "quantity": quantity})

    currency = CREDITS if paid else TL
    cart = {
        "items": items,
        "total": total,
        "currency": currency,
        "coupon_visible": not paid,
    }
    _map_for_write(state, "carts")[user_id] = cart
    return _success(
        state,
        {
            "items": [dict(item) for item in items],
            "total": total,
            "currency": currency,
            "coupon_visible": cart["coupon_visible"],
        },
    )


def _coupon_quote(state: dict, user: dict, cart: dict, action: dict) -> tuple[Any, bool]:
    """Return (checkout total, whether an active coupon changed the quote)."""
    original_total = cart.get("total", 0)
    if user.get("membership") == "paid" or cart.get("currency") != TL:
        return original_total, False

    coupons = state.get("coupons")
    coupon_code = action.get("coupon_code")
    if not isinstance(coupons, dict) or coupon_code not in coupons:
        return original_total, False
    coupon = coupons[coupon_code]
    if not isinstance(coupon, dict) or coupon.get("active") is not True:
        return original_total, False

    return max(0, original_total - coupon.get("amount_tl", 0)), True


def _thank_you(currency: Any, kind: Any, coupon_used: bool, total: Any) -> str:
    if currency == TL and coupon_used and total == 0:
        return "coupon"
    if kind == "membership":
        return "membership"
    if currency == CREDITS:
        return "credit"
    return "regular"


def _checkout(state: dict, action: dict) -> dict:
    user_id = action.get("user_id")
    user = _active_user(state, user_id)
    if user is None:
        return _reject(state, "invalid_user")

    order_id = action.get("order_id")
    orders = state.get("orders")
    if isinstance(orders, dict) and order_id in orders:
        # Existing orders are snapshots.  In particular, a replay cannot
        # replace either the original coupon route or its kind.
        order = orders[order_id]
        if not isinstance(order, dict):
            return _reject(state, "invalid_order")
        return _success(
            state,
            {
                "order_id": order_id,
                "payment_required": order.get("payment_required", False),
                "thank_you": order.get("thank_you", "regular"),
            },
        )

    carts = state.get("carts")
    if not isinstance(carts, dict) or user_id not in carts:
        return _reject(state, "missing_cart")
    cart = carts[user_id]
    if not isinstance(cart, dict):
        return _reject(state, "missing_cart")

    total, coupon_used = _coupon_quote(state, user, cart, action)
    currency = cart.get("currency")
    kind = action.get("kind", "regular")
    thank_you = _thank_you(currency, kind, coupon_used, total)
    order = {
        "user_id": user_id,
        "total": total,
        "currency": currency,
        "kind": kind,
        "status": "pending",
        "thank_you": thank_you,
        "payment_required": currency == TL and total > 0,
    }
    _map_for_write(state, "orders")[order_id] = order
    return _success(
        state,
        {
            "order_id": order_id,
            "payment_required": order["payment_required"],
            "thank_you": thank_you,
        },
    )


def _settle(state: dict, action: dict) -> dict:
    order_id = action.get("order_id")
    orders = state.get("orders")
    if not isinstance(orders, dict) or order_id not in orders:
        return _reject(state, "unknown_order")
    order = orders[order_id]
    if not isinstance(order, dict):
        return _reject(state, "invalid_order")

    event_id = action.get("event_id")
    # This check intentionally precedes account validation.  Replaying a
    # settlement remains harmless even when the account was later disabled.
    if order.get("status") == "settled" or _event_seen(state, event_id, "settlement"):
        return _success(state, {"order_id": order_id})

    user = _active_user(state, order.get("user_id"))
    if user is None:
        return _reject(state, "invalid_user")

    total = order.get("total", 0)
    currency = order.get("currency")
    payment = None

    if currency == CREDITS:
        balance = user.get("credits", 0)
        if balance < total:
            user["credits"] = 0
            payment = {
                "kind": "saved_payment_topup",
                "event_id": event_id,
                "order_id": order_id,
                "credits": total - balance,
            }
        else:
            user["credits"] = balance - total
    elif currency == TL and total > 0:
        payment = {
            "kind": "regular_payment",
            "event_id": event_id,
            "order_id": order_id,
            "amount_tl": total,
        }

    # The order, ledger, and optional payment are committed only after all
    # validation and account calculations have completed.
    order["status"] = "settled"
    _list_for_write(state, "ledger").append(
        {"event_id": event_id, "order_id": order_id, "kind": "settlement"}
    )
    if payment is not None:
        _list_for_write(state, "payments").append(payment)
    return _success(state, {"order_id": order_id})


def _renew(state: dict, action: dict) -> dict:
    user_id = action.get("user_id")
    event_id = action.get("event_id")

    # A renewal event is globally idempotent, not tied to the user in the
    # second request.  This prevents reusing a processed event as a new one.
    if _event_seen(state, event_id, "renewal"):
        return _success(state, {"user_id": user_id})

    user = _active_user(state, user_id)
    if user is None:
        return _reject(state, "invalid_user")

    date = action.get("date")
    old_expiry = user.get("credit_expiry")
    credits = user.get("credits", 0)
    if old_expiry is not None and old_expiry <= date:
        credits = 0

    user["credits"] = credits + action.get("package_credits", 0)
    user["membership"] = "paid"
    user["credit_expiry"] = action.get("new_expiry")
    _list_for_write(state, "ledger").append(
        {"event_id": event_id, "user_id": user_id, "kind": "renewal"}
    )
    return _success(state, {"user_id": user_id})


def _unknown_action(state: dict, action: dict) -> dict:
    return _reject(state, "unknown_action")


_HANDLERS = {
    "set_cart": _set_cart,
    "checkout": _checkout,
    "settle": _settle,
    "renew": _renew,
}


def apply_commerce(state: dict, action: dict) -> dict:
    """Apply one commerce action to the copied state."""
    handler = _HANDLERS.get(action.get("type"), _unknown_action)
    return handler(state, action)

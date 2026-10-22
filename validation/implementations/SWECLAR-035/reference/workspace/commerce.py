"""Commerce state transitions for carts, checkout, settlement, and renewal.

The functions in this module operate on the already-copied state supplied by
``solution.process_membership_action``.  They deliberately derive replay
information from the public order and ledger records rather than keeping
process-local state: every invocation is an independent JSON transition.
"""
from __future__ import annotations

from typing import Any, Dict, Optional



def _reject(state: dict, code: str) -> dict:
    """Return a rejected transition without changing business state."""
    state["error"] = {"code": code}
    return state



def _active_user(state: dict, user_id: Any) -> Optional[dict]:
    """Return an active user, or ``None`` for an invalid commerce user."""
    users = state.get("users")
    if not isinstance(users, dict) or user_id not in users:
        return None
    user = users[user_id]
    if not isinstance(user, dict) or user.get("status") != "active":
        return None
    return user



def _has_event(state: dict, event_id: Any, kind: str) -> bool:
    """Whether a public ledger entry already consumed this event for *kind*."""
    ledger = state.get("ledger")
    if not isinstance(ledger, list):
        return False
    return any(
        isinstance(entry, dict)
        and entry.get("kind") == kind
        and entry.get("event_id") == event_id
        for entry in ledger
    )



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
    total = 0
    items = []

    # Validate every line before writing the cart.  Thus a bad line cannot
    # replace a previously valid cart.
    for supplied in supplied_items:
        if not isinstance(supplied, dict):
            return _reject(state, "invalid_item")
        product_id = supplied.get("product_id")
        quantity = supplied.get("quantity")
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
        ):
            return _reject(state, "invalid_quantity")
        if product_id not in products:
            return _reject(state, "unavailable_product")
        product = products[product_id]
        if not isinstance(product, dict) or product.get("active", True) is False:
            return _reject(state, "unavailable_product")

        # Product prices/costs are the only values used.  In particular, no
        # client-supplied price field is copied into the resulting line.
        unit_price = product.get(price_field, 0)
        total += quantity * unit_price
        items.append({"product_id": product_id, "quantity": quantity})

    cart = {
        "items": items,
        "total": total,
        "currency": "credits" if paid else "TL",
        "coupon_visible": not paid,
    }
    state.setdefault("carts", {})[user_id] = cart
    state["result"] = {
        "items": [dict(item) for item in items],
        "total": total,
        "currency": cart["currency"],
        "coupon_visible": cart["coupon_visible"],
    }
    return state



def _checkout(state: dict, action: dict) -> dict:
    user_id = action.get("user_id")
    user = _active_user(state, user_id)
    if user is None:
        return _reject(state, "invalid_user")

    order_id = action.get("order_id")
    orders = state.get("orders")

    # An order is an idempotent checkout snapshot.  Once present, neither a
    # new coupon nor a changed kind on a replay may rewrite its route.
    if isinstance(orders, dict) and order_id in orders:
        order = orders[order_id]
        if not isinstance(order, dict):
            return _reject(state, "invalid_order")
        state["result"] = {
            "order_id": order_id,
            "payment_required": order.get("payment_required", False),
            "thank_you": order.get("thank_you", "regular"),
        }
        return state

    carts = state.get("carts")
    if not isinstance(carts, dict) or user_id not in carts:
        return _reject(state, "missing_cart")
    cart = carts[user_id]
    if not isinstance(cart, dict):
        return _reject(state, "missing_cart")

    currency = cart.get("currency")
    original_total = cart.get("total", 0)
    total = original_total
    coupon_applied = False

    # Coupons are a free-user/TL policy.  Credit carts never consult the
    # coupon map, even if a coupon code was supplied.
    if user.get("membership") != "paid" and currency == "TL":
        coupon_code = action.get("coupon_code")
        coupons = state.get("coupons")
        if isinstance(coupons, dict) and coupon_code in coupons:
            coupon = coupons[coupon_code]
            if isinstance(coupon, dict) and coupon.get("active") is True:
                amount = coupon.get("amount_tl", 0)
                total = max(0, original_total - amount)
                coupon_applied = True

    kind = action.get("kind", "regular")
    if currency == "TL" and coupon_applied and total == 0:
        thank_you = "coupon"
    elif kind == "membership":
        thank_you = "membership"
    elif currency == "credits":
        thank_you = "credit"
    else:
        thank_you = "regular"

    order = {
        "user_id": user_id,
        "total": total,
        "currency": currency,
        "kind": kind,
        "status": "pending",
        "thank_you": thank_you,
        "payment_required": currency == "TL" and total > 0,
    }
    state.setdefault("orders", {})[order_id] = order
    state["result"] = {
        "order_id": order_id,
        "payment_required": order["payment_required"],
        "thank_you": thank_you,
    }
    return state



def _settle(state: dict, action: dict) -> dict:
    order_id = action.get("order_id")
    orders = state.get("orders")
    if not isinstance(orders, dict) or order_id not in orders:
        return _reject(state, "unknown_order")
    order = orders[order_id]
    if not isinstance(order, dict):
        return _reject(state, "invalid_order")

    event_id = action.get("event_id")

    # Both kinds of replay are checked before user validation.  A replay is a
    # no-op even if the account has since been inactivated, and importantly it
    # cannot create a second ledger/payment record.
    if order.get("status") == "settled" or _has_event(state, event_id, "settlement"):
        state["result"] = {"order_id": order_id}
        return state

    user_id = order.get("user_id")
    user = _active_user(state, user_id)
    if user is None:
        return _reject(state, "invalid_user")

    total = order.get("total", 0)
    currency = order.get("currency")
    payment = None

    if currency == "credits":
        balance = user.get("credits", 0)
        if balance < total:
            shortfall = total - balance
            user["credits"] = 0
            payment = {
                "kind": "saved_payment_topup",
                "event_id": event_id,
                "order_id": order_id,
                "credits": shortfall,
            }
        else:
            user["credits"] = balance - total
    elif currency == "TL" and total > 0:
        payment = {
            "kind": "regular_payment",
            "event_id": event_id,
            "order_id": order_id,
            "amount_tl": total,
        }

    # All validation and balance calculation has completed before the first
    # business write below.
    order["status"] = "settled"
    state.setdefault("ledger", []).append(
        {"event_id": event_id, "order_id": order_id, "kind": "settlement"}
    )
    if payment is not None:
        state.setdefault("payments", []).append(payment)

    state["result"] = {"order_id": order_id}
    return state



def _renew(state: dict, action: dict) -> dict:
    user_id = action.get("user_id")
    event_id = action.get("event_id")

    if _has_event(state, event_id, "renewal"):
        state["result"] = {"user_id": user_id}
        return state

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

    state.setdefault("ledger", []).append(
        {"event_id": event_id, "user_id": user_id, "kind": "renewal"}
    )
    state["result"] = {"user_id": user_id}
    return state



def apply_commerce(state: dict, action: dict) -> dict:
    """Apply one commerce action to a copied state."""
    action_type = action.get("type")
    if action_type == "set_cart":
        return _set_cart(state, action)
    if action_type == "checkout":
        return _checkout(state, action)
    if action_type == "settle":
        return _settle(state, action)
    if action_type == "renew":
        return _renew(state, action)
    return _reject(state, "unknown_action")

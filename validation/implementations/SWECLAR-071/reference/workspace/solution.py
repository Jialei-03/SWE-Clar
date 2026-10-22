"""Reference implementation of the local pizzeria workflow.

The function in this module deliberately keeps all of the state in the value
passed by the caller.  The command line wrapper is responsible for storing
that value in SQLite; this module is consequently also useful as a small,
pure state-transition function in tests and in a web application.
"""

from copy import deepcopy
from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_FLOOR,
    ROUND_HALF_UP,
    localcontext,
)
import math
from typing import Any


# The state format is JSON-shaped, but Decimal is useful while pricing.  Keep
# the list of accepted numeric types explicit so that True/False never become
# prices, quantities, percentages, or point balances by Python coercion.
_NUMERIC_TYPES = (int, float, Decimal)


class _Reject(Exception):
    """Internal exception used to roll a transition back to its input value."""

    def __init__(self, code: str, message: str | None = None):
        self.code = code or "invalid"
        self.message = message or self.code
        super().__init__(self.message)


def _reject(code: str, message: str | None = None) -> None:
    raise _Reject(code, message)


def _is_nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _required_text(action: dict, name: str) -> str:
    if name not in action or not _is_nonempty_text(action[name]):
        _reject("invalid_" + name)
    return action[name]


def _collection(state: dict, name: str) -> dict:
    """Return a state collection, treating an absent optional one as empty."""

    value = state.get(name, {})
    if not isinstance(value, dict):
        _reject("invalid_" + name)
    return value


def _decimal(value: Any, code: str = "invalid_number", *, nonnegative: bool = False) -> Decimal:
    """Convert a JSON number to an exact-enough finite Decimal.

    Decimal(str(float)) avoids adding binary floating point noise to prices,
    while still accepting the ordinary int/float values produced by json.
    """

    if isinstance(value, bool) or not isinstance(value, _NUMERIC_TYPES):
        _reject(code)
    try:
        # str(Decimal) and str(int) are exact; str(float) is its JSON/Python
        # decimal spelling rather than the float's long binary expansion.
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        _reject(code)
    if not result.is_finite():
        _reject(code)
    if nonnegative and result < 0:
        _reject(code)
    return result


def _decimal_precision(*values: Decimal, extra: int = 20) -> int:
    """Choose enough working precision for finite monetary arithmetic."""

    required = extra
    for value in values:
        if not value.is_finite():
            continue
        digits = len(value.as_tuple().digits)
        exponent = value.as_tuple().exponent
        # Quantizing a value such as 1E+300 needs room for all integer places.
        required += max(digits, digits + max(0, exponent))
    return max(50, required)


def _json_number(value: Decimal) -> int | float:
    """Turn an internal Decimal into a JSON-compatible finite number."""

    if not value.is_finite():
        _reject("invalid_number")
    if value == value.to_integral_value():
        return int(value)
    result = float(value)
    if not math.isfinite(result):
        # A Decimal can represent a finite number outside the JSON float
        # range.  It cannot be emitted as a JSON numeric value by this API.
        _reject("invalid_number")
    return result


def _active_product(record: Any) -> bool:
    """Validate the active flag and say whether the record is active."""

    if not isinstance(record, dict):
        _reject("invalid_product")
    if "active" not in record:
        return False
    active = record["active"]
    if not isinstance(active, bool):
        _reject("invalid_product")
    return active


def _product_details(record: Any) -> tuple[str, str, Decimal]:
    """Validate and return (German name, English name, price)."""

    if not isinstance(record, dict):
        _reject("invalid_product")
    names = record.get("names")
    if not isinstance(names, dict):
        _reject("invalid_product")
    de = names.get("de")
    en = names.get("en")
    if not _is_nonempty_text(de) or not _is_nonempty_text(en):
        _reject("invalid_product")
    price = _decimal(record.get("price"), "invalid_price", nonnegative=True)
    return de, en, price


def _active_products(products: dict) -> dict:
    """Validate active definitions and return them by product id.

    Inactive products are intentionally not required to have a usable price or
    bilingual name: they cannot be selected or shown in the active catalogue.
    """

    active: dict = {}
    for product_id, record in products.items():
        if _active_product(record):
            _product_details(record)
            active[product_id] = record
    return active


def _active_product_by_id(products: dict, product_id: Any) -> tuple[dict, Decimal]:
    if product_id not in products:
        _reject("unknown_product")
    record = products[product_id]
    if not _active_product(record):
        _reject("inactive_product")
    _de, _en, price = _product_details(record)
    return record, price


def _customer(customers: dict, customer_id: str) -> dict:
    if customer_id not in customers:
        _reject("unknown_customer")
    record = customers[customer_id]
    if not isinstance(record, dict):
        _reject("invalid_customer")
    return record


def _points_field(customer: dict) -> tuple[str, int]:
    """Find the conventional point balance field and validate it.

    ``points`` is the public field used by the README.  The small set of
    aliases makes the transition tolerant of older synthetic fixtures without
    changing the public representation when ``points`` is present.
    """

    for field in ("points", "points_balance", "coin_points", "balance"):
        if field in customer:
            value = customer[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                _reject("invalid_points")
            return field, value
    return "points", 0


def _get_items(cart: Any) -> list:
    if not isinstance(cart, dict):
        _reject("invalid_cart")
    items = cart.get("items")
    if not isinstance(items, list):
        _reject("invalid_cart")
    return items


def _canonical_items_and_subtotal(items: list, products: dict) -> tuple[list[dict], Decimal]:
    """Validate cart lines, combine duplicate IDs, and calculate the price."""

    # Dict insertion order gives deterministic output while allowing the
    # contract's permitted duplicate-line normalization.
    quantities: dict[Any, int] = {}
    order: list[Any] = []
    prices: dict[Any, Decimal] = {}

    for line in items:
        if not isinstance(line, dict):
            _reject("invalid_item")
        if "product_id" not in line:
            _reject("invalid_item")
        product_id = line["product_id"]
        # IDs in the JSON contract are strings.  Requiring a nonempty string
        # also avoids unhashable/list IDs and ambiguous dictionary lookups.
        if not _is_nonempty_text(product_id):
            _reject("invalid_product_id")
        quantity = line.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            _reject("invalid_quantity")
        if product_id not in quantities:
            _record, price = _active_product_by_id(products, product_id)
            quantities[product_id] = 0
            order.append(product_id)
            prices[product_id] = price
        quantities[product_id] += quantity

    subtotal = Decimal(0)
    canonical: list[dict] = []
    with localcontext() as context:
        context.prec = _decimal_precision(
            *prices.values(),
            *(Decimal(quantity) for quantity in quantities.values()),
            extra=20 + len(order),
        )
        for product_id in order:
            quantity = quantities[product_id]
            subtotal += prices[product_id] * quantity
            canonical.append({"product_id": product_id, "quantity": quantity})
    return canonical, subtotal


def _coupon_percent(coupons: dict, coupon_code: str) -> Decimal:
    if coupon_code not in coupons:
        _reject("unknown_coupon")
    coupon = coupons[coupon_code]
    if not isinstance(coupon, dict) or coupon.get("active") is not True:
        _reject("invalid_coupon")
    percent = _decimal(coupon.get("percent"), "invalid_coupon")
    if percent < 0 or percent > 100:
        _reject("invalid_coupon")
    return percent


def _zone_minimum(zones: dict, zone_id: str) -> Decimal:
    if zone_id not in zones:
        _reject("unknown_zone")
    zone = zones[zone_id]
    if not isinstance(zone, dict) or zone.get("enabled") is not True:
        _reject("invalid_zone")
    return _decimal(zone.get("minimum"), "invalid_zone", nonnegative=True)


def _operation(action: dict) -> str:
    """Read the operation name, accepting the common public spellings."""

    found: list[tuple[str, Any]] = []
    for key in ("operation", "op", "action", "command", "type"):
        if key in action:
            found.append((key, action[key]))
    if not found:
        _reject("missing_operation")
    values = []
    for _key, value in found:
        if not isinstance(value, str):
            _reject("invalid_operation")
        values.append(value)
    if any(value != values[0] for value in values[1:]):
        _reject("conflicting_operation")
    return values[0]


def _base_copy(state: Any) -> dict:
    if not isinstance(state, dict):
        return {}
    try:
        return deepcopy(state)
    except Exception:
        # JSON-shaped input is copyable; retaining this guard ensures a bad
        # caller still receives the required nonempty error rather than a
        # partially-mutated object.
        return dict(state)


def _failure(state_copy: dict, rejection: _Reject) -> dict:
    state_copy.pop("result", None)
    state_copy["error"] = {"code": rejection.code, "message": rejection.message}
    return state_copy


def _success(state_copy: dict, result: dict) -> dict:
    state_copy.pop("error", None)
    state_copy["result"] = result
    return state_copy


def _do_catalog(working: dict, action: dict) -> dict:
    language = action.get("language")
    if language not in ("de", "en"):
        _reject("unsupported_language")
    products = _collection(working, "products")
    active = _active_products(products)
    rows = []
    for product_id, record in active.items():
        de, en, price = _product_details(record)
        rows.append(
            {
                "product_id": product_id,
                "name": de if language == "de" else en,
                "price": _json_number(price),
            }
        )
    return {"products": rows}


def _do_set_cart(working: dict, action: dict) -> dict:
    customer_id = _required_text(action, "customer_id")
    if "items" not in action or not isinstance(action["items"], list):
        _reject("invalid_items")

    customers = _collection(working, "customers")
    _customer(customers, customer_id)
    products = _collection(working, "products")
    items, subtotal = _canonical_items_and_subtotal(action["items"], products)

    carts = _collection(working, "carts")
    # Work on a fresh collection only after every validation above succeeds.
    if "carts" not in working:
        working["carts"] = carts
    carts[customer_id] = {
        "items": items,
        "subtotal": _json_number(subtotal),
    }
    return {"subtotal": _json_number(subtotal)}


def _do_checkout(working: dict, action: dict) -> dict:
    customer_id = _required_text(action, "customer_id")
    order_id = _required_text(action, "order_id")
    mode = action.get("mode")
    if mode not in ("pickup", "preorder", "delivery"):
        _reject("invalid_mode")

    customers = _collection(working, "customers")
    customer = _customer(customers, customer_id)
    _points_name, points = _points_field(customer)

    orders = _collection(working, "orders")
    if order_id in orders:
        _reject("duplicate_order_id")
    carts = _collection(working, "carts")
    if customer_id not in carts:
        _reject("missing_cart")
    cart = carts[customer_id]
    raw_items = _get_items(cart)
    if not raw_items:
        _reject("empty_cart")

    products = _collection(working, "products")
    canonical_items, subtotal = _canonical_items_and_subtotal(raw_items, products)
    # canonical_items is intentionally calculated even though the checkout
    # does not rewrite the cart: it is the revalidation of the current cart.
    del canonical_items

    if mode == "delivery":
        if "zone_id" not in action or not _is_nonempty_text(action["zone_id"]):
            _reject("invalid_zone")
        zone_id = action["zone_id"]
        minimum = _zone_minimum(_collection(working, "zones"), zone_id)
        # This check is deliberately before coupon and point discounts.
        if subtotal < minimum:
            _reject("delivery_minimum")
    else:
        zone_id = None

    coupon_code: str | None = None
    percent = Decimal(0)
    if action.get("coupon_code") is not None:
        supplied_coupon = action["coupon_code"]
        if not _is_nonempty_text(supplied_coupon):
            _reject("invalid_coupon")
        coupon_code = supplied_coupon
        percent = _coupon_percent(_collection(working, "coupons"), coupon_code)

    redeem_points = action.get("redeem_points", 0)
    if isinstance(redeem_points, bool) or not isinstance(redeem_points, int) or redeem_points < 0:
        _reject("invalid_redeem_points")
    if redeem_points > points:
        _reject("insufficient_points")

    with localcontext() as context:
        context.prec = _decimal_precision(
            subtotal,
            percent,
            Decimal(redeem_points),
            extra=30,
        )
        discounted = subtotal * (Decimal(1) - percent / Decimal(100))
        total_before_rounding = discounted - Decimal(redeem_points) / Decimal(100)
        if total_before_rounding < 0:
            total_before_rounding = Decimal(0)
        total = total_before_rounding.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    order = {
        "customer_id": customer_id,
        "mode": mode,
        "subtotal": _json_number(subtotal),
        "total": _json_number(total),
        "coupon_code": coupon_code,
        "redeemed_points": redeem_points,
        "status": "pending",
        "paid": False,
    }
    if zone_id is not None:
        order["zone_id"] = zone_id
    if "orders" not in working:
        working["orders"] = orders
    orders[order_id] = order
    return {"order_id": order_id}


def _order_event(order: dict) -> str | None:
    """Return an event stored on an order, if one is present."""

    for field in ("_payment_event_id", "payment_event_id"):
        if field in order:
            value = order[field]
            if not _is_nonempty_text(value):
                _reject("invalid_payment_event")
            return value
    return None


def _known_payment_event(orders: dict, event_id: str) -> tuple[Any, bool] | None:
    """Find an event in order metadata.

    The bool says whether the event belongs to a paid order.  Scanning orders
    keeps the association persistent across CLI processes without requiring a
    particular extra top-level collection in the input state.
    """

    found = None
    for order_id, order in orders.items():
        if not isinstance(order, dict):
            _reject("invalid_order")
        event = _order_event(order)
        if event == event_id:
            paid = order.get("paid", False)
            if not isinstance(paid, bool):
                _reject("invalid_order")
            if found is not None and found[0] != order_id:
                _reject("payment_event_conflict")
            found = (order_id, paid)
    return found


def _do_mark_paid(working: dict, action: dict) -> dict:
    order_id = _required_text(action, "order_id")
    payment_event_id = _required_text(action, "payment_event_id")

    orders = _collection(working, "orders")
    if order_id not in orders:
        _reject("unknown_order")
    order = orders[order_id]
    if not isinstance(order, dict):
        _reject("invalid_order")

    paid = order.get("paid", False)
    if not isinstance(paid, bool):
        _reject("invalid_order")
    own_event = _order_event(order)
    event_owner = _known_payment_event(orders, payment_event_id)

    if paid:
        # A replay is successful only for the exact event recorded for this
        # order.  It must not touch balances or bookkeeping again.
        if own_event == payment_event_id or (
            event_owner is not None and event_owner[0] == order_id
        ):
            return {"order_id": order_id, "paid": True}
        _reject("order_already_paid")

    if own_event is not None:
        # An unpaid order with an existing association is inconsistent and
        # must not allow an event to be reassigned.
        _reject("payment_event_conflict")
    if event_owner is not None:
        _reject("payment_event_conflict")

    customer_id = order.get("customer_id")
    if not _is_nonempty_text(customer_id):
        _reject("invalid_order")
    customer = _customer(_collection(working, "customers"), customer_id)

    redeemed_points = order.get("redeemed_points", 0)
    if (
        isinstance(redeemed_points, bool)
        or not isinstance(redeemed_points, int)
        or redeemed_points < 0
    ):
        _reject("invalid_order")
    total = _decimal(order.get("total"), "invalid_order", nonnegative=True)
    points_field, points = _points_field(customer)
    if redeemed_points > points:
        _reject("insufficient_points")

    earned_decimal = total.to_integral_value(rounding=ROUND_FLOOR)
    earned = int(earned_decimal)
    customer[points_field] = points - redeemed_points + earned
    order["paid"] = True
    # The underscore distinguishes the implementation association from the
    # public payment event ingestion action; its format is intentionally free.
    order["_payment_event_id"] = payment_event_id
    return {"order_id": order_id, "paid": True}


def _do_reserve(working: dict, action: dict) -> dict:
    reservation_id = _required_text(action, "reservation_id")
    slot = _required_text(action, "slot")
    party_size = action.get("party_size")
    if isinstance(party_size, bool) or not isinstance(party_size, int) or party_size <= 0:
        _reject("invalid_party_size")

    reservations = _collection(working, "reservations")
    if reservation_id in reservations:
        _reject("duplicate_reservation_id")
    for existing in reservations.values():
        if not isinstance(existing, dict):
            _reject("invalid_reservation")
        existing_slot = existing.get("slot")
        if existing_slot == slot:
            _reject("reservation_conflict")

    if "reservations" not in working:
        working["reservations"] = reservations
    reservations[reservation_id] = {"slot": slot, "party_size": party_size}
    return {"reservation_id": reservation_id}


def _do_advance_order(working: dict, action: dict) -> dict:
    actor_id = _required_text(action, "actor_id")
    order_id = _required_text(action, "order_id")
    new_status = action.get("status")
    statuses = ("pending", "accepted", "preparing", "ready", "completed")
    if new_status not in statuses:
        _reject("invalid_status")

    admins = working.get("admins", [])
    if not isinstance(admins, list):
        _reject("invalid_admins")
    if actor_id not in admins:
        _reject("unauthorized")

    orders = _collection(working, "orders")
    if order_id not in orders or not isinstance(orders[order_id], dict):
        _reject("unknown_order")
    order = orders[order_id]
    current = order.get("status")
    if current not in statuses:
        _reject("invalid_order_status")
    current_index = statuses.index(current)
    target_index = statuses.index(new_status)
    if target_index < current_index or target_index > current_index + 1:
        _reject("invalid_transition")
    if target_index == current_index:
        # Same-state retries are explicitly allowed as no-ops.
        return {"order_id": order_id, "status": current}
    order["status"] = new_status
    return {"order_id": order_id, "status": new_status}


def process_pizzeria_action(state: dict, action: dict) -> dict:
    """Apply one pizzeria action and return the complete next state.

    The caller's ``state`` and ``action`` are never mutated.  Every operation
    validates before committing its business changes to a deep copy; a
    rejection therefore returns the original business collections alongside a
    nonempty ``error.code``.
    """

    if not isinstance(state, dict):
        return {"error": {"code": "invalid_state", "message": "state must be an object"}}
    state_copy = _base_copy(state)
    if not isinstance(action, dict):
        return _failure(state_copy, _Reject("invalid_action"))

    try:
        operation = _operation(action)
        # Work only on the copy.  Individual helpers mutate it after their
        # validation gates, so an exception is safe to discard here.
        working = deepcopy(state_copy)
        if operation == "catalog":
            result = _do_catalog(working, action)
        elif operation == "set_cart":
            result = _do_set_cart(working, action)
        elif operation == "checkout":
            result = _do_checkout(working, action)
        elif operation == "mark_paid":
            result = _do_mark_paid(working, action)
        elif operation == "reserve":
            result = _do_reserve(working, action)
        elif operation == "advance_order":
            result = _do_advance_order(working, action)
        else:
            _reject("unknown_operation")
        return _success(working, result)
    except _Reject as rejection:
        return _failure(state_copy, rejection)
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError) as exc:
        # Malformed synthetic state/action is a rejection, never a partial
        # success.  Do not expose a potentially empty exception as the code.
        code = "invalid_input"
        if isinstance(exc, KeyError):
            code = "invalid_input"
        return _failure(state_copy, _Reject(code, str(exc) or code))


__all__ = ["process_pizzeria_action"]

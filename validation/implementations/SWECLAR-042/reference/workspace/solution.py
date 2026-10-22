"""Reference implementation for the local review-workflow ledger.

The function in this module deliberately treats the actor fields in an action as
already-authenticated identity assertions.  It only checks that the asserted
user is present and has an active session in the supplied local state; it does
not attempt to authenticate anybody or to process a payment externally.
"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math


_MISSING = object()
_TWO_PLACES = Decimal("0.01")


def _error(code: str) -> dict:
    """Return the public rejection envelope."""
    # Codes are intentionally short and stable, but the public contract does
    # not attach meaning to their spelling beyond being non-empty strings.
    return {"error": {"code": code}}


def _identifier(value) -> bool:
    """IDs and asset references in this protocol are non-empty strings."""
    return isinstance(value, str) and bool(value)


def _field(action: dict, name: str):
    value = action.get(name, _MISSING)
    return value


def _decimal_number(value, *, currency: bool = False):
    """Parse a JSON number without introducing binary floating-point errors.

    ``None`` is used as the invalid sentinel.  Boolean values are excluded
    even though bool is a subclass of int in Python.
    """
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, Decimal)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None

    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None

    if not number.is_finite() or number < 0:
        return None

    if currency:
        # Comparing with a two-place quantization permits harmless trailing
        # zeroes (for example, Decimal("1.2300")) while rejecting 1.235.
        try:
            if number != number.quantize(_TWO_PLACES):
                return None
        except (InvalidOperation, ValueError):
            return None

    return number


def _fraction(value):
    """Parse the supplied fee fraction and ensure it is in [0, 1]."""
    number = _decimal_number(value)
    if number is None or number > Decimal("1"):
        return None
    return number


def _state_number(number: Decimal):
    """Convert a Decimal to a JSON-compatible, non-lossy-enough currency value."""
    # Currency values have at most two places.  Integral values are emitted as
    # ints and other values as floats, keeping the state JSON-native (the
    # adapter serializes it with json.dumps and cannot store Decimal objects).
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def _mapping(state: dict, name: str):
    """Read a state mapping, treating an omitted collection as empty."""
    if name not in state:
        return {}
    value = state[name]
    return value if isinstance(value, dict) else None


def _list_collection(state: dict, name: str):
    """Read a state list, treating an omitted collection as empty."""
    if name not in state:
        return []
    value = state[name]
    return value if isinstance(value, list) else None


def _ensure_mapping(state: dict, name: str):
    """Get/create a mapping in a cloned state."""
    if name not in state:
        state[name] = {}
    value = state[name]
    return value if isinstance(value, dict) else None


def _ensure_list(state: dict, name: str):
    """Get/create a list in a cloned state."""
    if name not in state:
        state[name] = []
    value = state[name]
    return value if isinstance(value, list) else None


def _active_actor(state: dict, user_id: str) -> bool:
    """Check the local identity invariant for an acting user."""
    users = state.get("users", _MISSING)
    sessions = state.get("sessions", _MISSING)
    if not isinstance(users, dict) or not isinstance(sessions, list):
        return False
    return user_id in users and user_id in sessions


def _clone(state: dict):
    try:
        return deepcopy(state)
    except Exception:
        # Inputs are JSON-shaped in the public interface.  This guard keeps a
        # malformed direct Python call a rejection rather than an exception.
        return None


def _required_id(action: dict, name: str):
    value = _field(action, name)
    return value if _identifier(value) else _MISSING


def _valid_images(value):
    if not isinstance(value, list) or len(value) > 5:
        return False
    # References are deliberately only recorded, never opened or uploaded.
    return all(_identifier(image) for image in value)


def _held_payment_for_listing(state: dict, listing_id: str):
    """Return the sole held payment for a listing, or an error sentinel.

    A listing has one agreed payment in the normal workflow.  Treating an
    ambiguous state as invalid avoids releasing the wrong event.
    """
    payments = _mapping(state, "payments")
    if payments is None:
        return _MISSING

    matches = []
    for key, payment in payments.items():
        if not isinstance(payment, dict):
            # Unrelated malformed records do not affect this transition.  A
            # record that claims this listing, however, cannot be used safely.
            continue
        if payment.get("listing_id") == listing_id and payment.get("status") == "held":
            matches.append((key, payment))

    if len(matches) != 1:
        return _MISSING
    return matches[0]


def _create_listing(state: dict, action: dict) -> dict:
    listing_id = _required_id(action, "listing_id")
    owner_id = _required_id(action, "owner_id")
    raw_price = _field(action, "price")
    price = _decimal_number(raw_price, currency=True)
    if listing_id is _MISSING or owner_id is _MISSING or price is None:
        return _error("invalid_listing")
    if not _active_actor(state, owner_id):
        return _error("unauthorized_actor")

    listings = _mapping(state, "listings")
    if listings is None:
        return _error("invalid_state")
    if listing_id in listings:
        return _error("listing_exists")

    next_state = _clone(state)
    if next_state is None:
        return _error("invalid_state")
    next_listings = _ensure_mapping(next_state, "listings")
    if next_listings is None:
        return _error("invalid_state")
    next_listings[listing_id] = {
        "owner_id": owner_id,
        "price": _state_number(price),
        "status": "open",
    }
    return next_state


def _apply(state: dict, action: dict) -> dict:
    application_id = _required_id(action, "application_id")
    listing_id = _required_id(action, "listing_id")
    reviewer_id = _required_id(action, "reviewer_id")
    if application_id is _MISSING or listing_id is _MISSING or reviewer_id is _MISSING:
        return _error("invalid_application")
    if not _active_actor(state, reviewer_id):
        return _error("unauthorized_actor")

    listings = _mapping(state, "listings")
    applications = _mapping(state, "applications")
    if listings is None or applications is None:
        return _error("invalid_state")
    listing = listings.get(listing_id, _MISSING)
    if listing is _MISSING:
        return _error("listing_not_found")
    if not isinstance(listing, dict):
        return _error("invalid_state")
    if listing.get("status") != "open":
        return _error("listing_not_open")
    if listing.get("owner_id") == reviewer_id:
        return _error("owner_cannot_apply")
    if application_id in applications:
        return _error("application_exists")

    next_state = _clone(state)
    if next_state is None:
        return _error("invalid_state")
    next_applications = _ensure_mapping(next_state, "applications")
    if next_applications is None:
        return _error("invalid_state")
    next_applications[application_id] = {
        "listing_id": listing_id,
        "reviewer_id": reviewer_id,
        "status": "pending",
    }
    return next_state


def _accept(state: dict, action: dict) -> dict:
    application_id = _required_id(action, "application_id")
    owner_id = _required_id(action, "owner_id")
    if application_id is _MISSING or owner_id is _MISSING:
        return _error("invalid_acceptance")
    if not _active_actor(state, owner_id):
        return _error("unauthorized_actor")

    listings = _mapping(state, "listings")
    applications = _mapping(state, "applications")
    reviews = _mapping(state, "reviews")
    if listings is None or applications is None or reviews is None:
        return _error("invalid_state")

    application = applications.get(application_id, _MISSING)
    if application is _MISSING:
        return _error("application_not_found")
    if not isinstance(application, dict):
        return _error("invalid_state")
    if application.get("status") != "pending":
        return _error("application_not_pending")

    listing_id = application.get("listing_id", _MISSING)
    reviewer_id = application.get("reviewer_id", _MISSING)
    if not _identifier(listing_id) or not _identifier(reviewer_id):
        return _error("invalid_state")
    listing = listings.get(listing_id, _MISSING)
    if listing is _MISSING:
        return _error("listing_not_found")
    if not isinstance(listing, dict):
        return _error("invalid_state")
    if listing.get("owner_id") != owner_id:
        return _error("not_listing_owner")
    if listing.get("status") != "open":
        return _error("listing_not_open")
    if application_id in reviews:
        return _error("review_exists")

    next_state = _clone(state)
    if next_state is None:
        return _error("invalid_state")
    next_applications = _ensure_mapping(next_state, "applications")
    next_listings = _ensure_mapping(next_state, "listings")
    next_reviews = _ensure_mapping(next_state, "reviews")
    if next_applications is None or next_listings is None or next_reviews is None:
        return _error("invalid_state")

    next_applications[application_id]["status"] = "accepted"
    next_listing = next_listings[listing_id]
    next_listing["status"] = "awaiting_payment"
    next_listing["active_review_id"] = application_id
    next_reviews[application_id] = {
        "listing_id": listing_id,
        "reviewer_id": reviewer_id,
        "status": "active",
        "images": [],
    }
    return next_state


def _submit_review(state: dict, action: dict) -> dict:
    review_id = _required_id(action, "review_id")
    reviewer_id = _required_id(action, "reviewer_id")
    raw_images = _field(action, "images")
    if review_id is _MISSING or reviewer_id is _MISSING or raw_images is _MISSING:
        return _error("invalid_submission")
    if not _valid_images(raw_images):
        return _error("invalid_images")

    has_url = "url" in action and action.get("url") is not None
    url = action.get("url") if has_url else None
    if has_url and not isinstance(url, str):
        return _error("invalid_url")
    if not _active_actor(state, reviewer_id):
        return _error("unauthorized_actor")

    reviews = _mapping(state, "reviews")
    listings = _mapping(state, "listings")
    if reviews is None or listings is None:
        return _error("invalid_state")
    review = reviews.get(review_id, _MISSING)
    if review is _MISSING:
        return _error("review_not_found")
    if not isinstance(review, dict):
        return _error("invalid_state")
    if review.get("status") != "active":
        return _error("review_not_active")
    if review.get("reviewer_id") != reviewer_id:
        return _error("not_review_reviewer")

    listing_id = review.get("listing_id", _MISSING)
    if not _identifier(listing_id):
        return _error("invalid_state")
    listing = listings.get(listing_id, _MISSING)
    if listing is _MISSING or not isinstance(listing, dict):
        return _error("listing_not_found" if listing is _MISSING else "invalid_state")
    if listing.get("active_review_id") != review_id:
        return _error("review_not_active")
    if listing.get("status") != "in_review":
        return _error("payment_not_held")
    held = _held_payment_for_listing(state, listing_id)
    if held is _MISSING:
        return _error("payment_not_held")
    if held[1].get("receiver_id") != reviewer_id:
        return _error("payment_not_held")

    next_state = _clone(state)
    if next_state is None:
        return _error("invalid_state")
    next_reviews = _ensure_mapping(next_state, "reviews")
    if next_reviews is None:
        return _error("invalid_state")
    next_review = next_reviews[review_id]
    next_review["status"] = "submitted"
    next_review["images"] = list(raw_images)
    if has_url:
        next_review["url"] = url
    else:
        # A fresh accepted review has no URL.  Removing a pre-existing one in
        # a hand-built state makes an omitted optional field mean "omitted".
        next_review.pop("url", None)

    return {
        **next_state,
        "result": {
            "image_count": len(raw_images),
            "url_skipped": not has_url,
        },
    }


def _payment_details_match(payment: dict, event_id: str, listing_id: str,
                           payer_id: str, amount: Decimal) -> bool:
    if payment.get("event_id") != event_id:
        return False
    if payment.get("listing_id") != listing_id or payment.get("payer_id") != payer_id:
        return False
    existing_gross = _decimal_number(payment.get("gross"), currency=True)
    return existing_gross is not None and existing_gross == amount


def _payment(state: dict, action: dict) -> dict:
    event_id = _required_id(action, "event_id")
    listing_id = _required_id(action, "listing_id")
    payer_id = _required_id(action, "payer_id")
    raw_amount = _field(action, "amount")
    amount = _decimal_number(raw_amount, currency=True)
    if (event_id is _MISSING or listing_id is _MISSING or payer_id is _MISSING
            or amount is None):
        return _error("invalid_payment")
    if not _active_actor(state, payer_id):
        return _error("unauthorized_actor")

    listings = _mapping(state, "listings")
    payments = _mapping(state, "payments")
    processed_events = _list_collection(state, "processed_events")
    if listings is None or payments is None or processed_events is None:
        return _error("invalid_state")

    # Idempotency is keyed by the event ID.  It is checked before workflow
    # status so replaying a successfully committed event is a true no-op.
    if event_id in payments:
        existing = payments[event_id]
        if not isinstance(existing, dict):
            return _error("invalid_state")
        if _payment_details_match(existing, event_id, listing_id, payer_id, amount):
            next_state = _clone(state)
            return next_state if next_state is not None else _error("invalid_state")
        return _error("payment_event_conflict")
    if event_id in processed_events:
        # There is no safe way to prove that an event with no corresponding
        # record is identical, so it cannot be reused.
        return _error("payment_event_conflict")

    listing = listings.get(listing_id, _MISSING)
    if listing is _MISSING:
        return _error("listing_not_found")
    if not isinstance(listing, dict):
        return _error("invalid_state")
    if listing.get("owner_id") != payer_id:
        return _error("not_listing_owner")
    if listing.get("status") != "awaiting_payment":
        return _error("listing_not_payable")

    price = _decimal_number(listing.get("price"), currency=True)
    if price is None or price != amount:
        return _error("amount_mismatch")

    active_review_id = listing.get("active_review_id", _MISSING)
    if not _identifier(active_review_id):
        return _error("review_not_active")
    reviews = _mapping(state, "reviews")
    if reviews is None:
        return _error("invalid_state")
    review = reviews.get(active_review_id, _MISSING)
    if review is _MISSING or not isinstance(review, dict):
        return _error("review_not_found" if review is _MISSING else "invalid_state")
    if review.get("status") != "active":
        return _error("review_not_active")
    if review.get("listing_id") != listing_id:
        return _error("invalid_state")
    receiver_id = review.get("reviewer_id", _MISSING)
    if not _identifier(receiver_id):
        return _error("invalid_state")

    fee_rate = _fraction(state.get("fee_rate", _MISSING))
    if fee_rate is None:
        return _error("invalid_fee_rate")
    platform_fee = (amount * fee_rate).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    eligible = amount - platform_fee

    next_state = _clone(state)
    if next_state is None:
        return _error("invalid_state")
    next_listings = _ensure_mapping(next_state, "listings")
    next_payments = _ensure_mapping(next_state, "payments")
    next_events = _ensure_list(next_state, "processed_events")
    if next_listings is None or next_payments is None or next_events is None:
        return _error("invalid_state")

    next_payments[event_id] = {
        "event_id": event_id,
        "listing_id": listing_id,
        "payer_id": payer_id,
        "receiver_id": receiver_id,
        "gross": _state_number(amount),
        "platform_fee": _state_number(platform_fee),
        "eligible": _state_number(eligible),
        "status": "held",
    }
    next_listings[listing_id]["status"] = "in_review"
    next_events.append(event_id)
    return next_state


def _approve_review(state: dict, action: dict) -> dict:
    listing_id = _required_id(action, "listing_id")
    owner_id = _required_id(action, "owner_id")
    if listing_id is _MISSING or owner_id is _MISSING:
        return _error("invalid_approval")
    if not _active_actor(state, owner_id):
        return _error("unauthorized_actor")

    listings = _mapping(state, "listings")
    if listings is None:
        return _error("invalid_state")
    listing = listings.get(listing_id, _MISSING)
    if listing is _MISSING:
        return _error("listing_not_found")
    if not isinstance(listing, dict):
        return _error("invalid_state")
    if listing.get("owner_id") != owner_id:
        return _error("not_listing_owner")

    # Approval is idempotent after completion.  Authentication and ownership
    # are still checked above, so an unknown actor cannot use this as a read
    # or write primitive.
    if listing.get("status") == "completed":
        next_state = _clone(state)
        return next_state if next_state is not None else _error("invalid_state")
    if listing.get("status") != "in_review":
        return _error("listing_not_reviewable")

    active_review_id = listing.get("active_review_id", _MISSING)
    if not _identifier(active_review_id):
        return _error("review_not_found")
    reviews = _mapping(state, "reviews")
    if reviews is None:
        return _error("invalid_state")
    review = reviews.get(active_review_id, _MISSING)
    if review is _MISSING:
        return _error("review_not_found")
    if not isinstance(review, dict):
        return _error("invalid_state")
    if review.get("status") != "submitted":
        return _error("review_not_submitted")

    held = _held_payment_for_listing(state, listing_id)
    if held is _MISSING:
        return _error("payment_not_held")
    payment_key, payment = held
    receiver_id = payment.get("receiver_id", _MISSING)
    if not _identifier(receiver_id) or receiver_id != review.get("reviewer_id"):
        return _error("invalid_state")
    event_id = payment.get("event_id", _MISSING)
    if not _identifier(event_id):
        return _error("invalid_state")
    eligible = _decimal_number(payment.get("eligible"), currency=True)
    if eligible is None:
        return _error("invalid_state")

    payouts = _list_collection(state, "payouts")
    if payouts is None:
        return _error("invalid_state")
    payout_exists = False
    for payout in payouts:
        if isinstance(payout, dict) and payout.get("event_id") == event_id:
            payout_exists = True
            break

    next_state = _clone(state)
    if next_state is None:
        return _error("invalid_state")
    next_listings = _ensure_mapping(next_state, "listings")
    next_reviews = _ensure_mapping(next_state, "reviews")
    next_payments = _ensure_mapping(next_state, "payments")
    next_payouts = _ensure_list(next_state, "payouts")
    if (next_listings is None or next_reviews is None or next_payments is None
            or next_payouts is None):
        return _error("invalid_state")

    next_listings[listing_id]["status"] = "completed"
    next_reviews[active_review_id]["status"] = "approved"
    # Use the event key when possible, while retaining the public event_id
    # linkage from the record.
    payment_record = next_payments.get(payment_key)
    if not isinstance(payment_record, dict):
        return _error("invalid_state")
    payment_record["status"] = "released"
    if not payout_exists:
        next_payouts.append({
            "event_id": event_id,
            "listing_id": listing_id,
            "receiver_id": receiver_id,
            "amount": _state_number(eligible),
        })
    return next_state


def _profile_image(state: dict, action: dict) -> dict:
    user_id = _required_id(action, "user_id")
    image_ref = _field(action, "image_ref")
    if user_id is _MISSING or not _identifier(image_ref):
        return _error("invalid_profile_image")
    if not _active_actor(state, user_id):
        return _error("unauthorized_actor")
    users = state.get("users", _MISSING)
    if not isinstance(users, dict) or user_id not in users:
        return _error("user_not_found")
    if not isinstance(users[user_id], dict):
        return _error("invalid_state")

    next_state = _clone(state)
    if next_state is None:
        return _error("invalid_state")
    next_users = next_state.get("users")
    if not isinstance(next_users, dict) or not isinstance(next_users[user_id], dict):
        return _error("invalid_state")
    next_users[user_id]["profile_image"] = image_ref
    return next_state


def _delete_account(state: dict, action: dict) -> dict:
    user_id = _required_id(action, "user_id")
    if user_id is _MISSING:
        return _error("invalid_deletion")
    if not _active_actor(state, user_id):
        return _error("unauthorized_actor")
    users = state.get("users", _MISSING)
    sessions = state.get("sessions", _MISSING)
    if not isinstance(users, dict) or user_id not in users or not isinstance(sessions, list):
        return _error("invalid_state")

    next_state = _clone(state)
    if next_state is None:
        return _error("invalid_state")
    next_users = next_state.get("users")
    next_sessions = next_state.get("sessions")
    if not isinstance(next_users, dict) or not isinstance(next_sessions, list):
        return _error("invalid_state")
    del next_users[user_id]
    next_state["sessions"] = [session for session in next_sessions if session != user_id]
    return next_state


def process_review_action(state: dict, action: dict) -> dict:
    """Apply exactly one local review-workflow action.

    Every successful path works on a deep copy.  Rejected actions return only
    an error envelope, which is also the signal used by ``ledger.py`` not to
    persist a transition.
    """
    if not isinstance(state, dict) or not isinstance(action, dict):
        return _error("invalid_input")

    action_type = action.get("type", _MISSING)
    if not isinstance(action_type, str):
        return _error("unknown_action")
    handlers = {
        "create_listing": _create_listing,
        "apply": _apply,
        "accept": _accept,
        "submit_review": _submit_review,
        "payment": _payment,
        "approve_review": _approve_review,
        "profile_image": _profile_image,
        "delete_account": _delete_account,
    }
    handler = handlers.get(action_type)
    if handler is None:
        return _error("unknown_action")
    outcome = handler(state, action)
    if isinstance(outcome, dict) and "error" in outcome:
        return {**deepcopy(state), **outcome}
    return outcome

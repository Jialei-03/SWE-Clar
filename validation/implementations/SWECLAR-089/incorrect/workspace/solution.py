"""Immutable workflow rules for the lesson scheduling backend.

The function in this module deliberately knows nothing about HTTP, SQLite, or
provider credentials.  It receives a private state snapshot, performs the
business checks, and returns a new snapshot.  Provider calls are made through
the small ``StudioClient``-compatible object supplied by the caller; state is
only changed after all provider acknowledgements needed for an operation have
succeeded.
"""

from copy import deepcopy
from datetime import datetime
import re
from urllib.parse import urlsplit


# These are the pieces of state which are owned by the workflow.  Missing
# collections are useful for older initial-state files, while a wrong type is
# an invalid state rather than something which should be silently replaced.
ROOT_TYPES = {
    "users": dict,
    "packages": dict,
    "availability": dict,
    "bookings": dict,
    "credits": dict,
    "processed_payments": dict,
    "ledger": list,
    "emails": list,
    "audit": list,
}

# An ISO timestamp used by this component must carry an explicit offset.  The
# colonless form is accepted as well as the usual ISO ``+HH:MM`` form; both
# are numeric timezone offsets.
_OFFSET_SUFFIX = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")


class _WorkflowError(Exception):
    """An expected business/provider validation failure."""


class _ProviderError(Exception):
    """A provider call or provider acknowledgement failed."""


def _fail(out, code):
    """Return an error snapshot without exposing exception/provider details."""

    out.pop("result", None)
    out["error"] = {"code": code}
    return out


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _safe_get(mapping, key, default=None):
    """dict.get which also handles unhashable JSON values."""

    if not isinstance(mapping, dict):
        return default
    try:
        return mapping.get(key, default)
    except (TypeError, ValueError):
        return default


def _user(state, user_id, role=None):
    value = _safe_get(state.get("users"), user_id)
    if not isinstance(value, dict):
        return None
    if role is not None and value.get("role") != role:
        return None
    return value


def _is_admin(user):
    return isinstance(user, dict) and user.get("role") in {"admin", "administrator"}


def _positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonnegative_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _parse_timestamp(value):
    """Parse an explicitly zoned ISO timestamp or raise ``_WorkflowError``."""

    if not isinstance(value, str):
        raise _WorkflowError("invalid timestamp")
    value = value.strip()
    if not _OFFSET_SUFFIX.search(value):
        raise _WorkflowError("timestamp needs an offset")

    # datetime.fromisoformat supports the numeric forms.  Replacing Z avoids
    # relying on the Python version's support for the UTC designator.
    iso_value = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(iso_value)
    except (TypeError, ValueError, OverflowError):
        raise _WorkflowError("invalid timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _WorkflowError("timestamp needs an offset")
    return parsed


def _parse_slot(value):
    """Return ``(canonical_slot, start, end)`` for a slot string."""

    if not isinstance(value, str) or not value.strip():
        raise _WorkflowError("invalid slot")
    pieces = value.strip().split("/")
    if len(pieces) != 2:
        raise _WorkflowError("invalid slot")
    start_text, end_text = pieces[0].strip(), pieces[1].strip()
    if not start_text or not end_text:
        raise _WorkflowError("invalid slot")
    start = _parse_timestamp(start_text)
    end = _parse_timestamp(end_text)
    if not start < end:
        raise _WorkflowError("slot is not increasing")
    return f"{start_text}/{end_text}", start, end


def _overlap(first_start, first_end, second_start, second_end):
    # Intervals are half-open.  In particular, end == other_start is safe.
    return first_start < second_end and second_start < first_end


def _normalise_slots(slots):
    """Validate and canonicalise an availability list.

    Availability entries are trimmed at both timestamp boundaries.  Duplicate
    entries are harmless and are collapsed; two distinct overlapping entries
    are rejected rather than creating ambiguous open intervals.
    """

    if not isinstance(slots, list):
        raise _WorkflowError("invalid availability")
    parsed = []
    seen = set()
    for raw_slot in slots:
        canonical, start, end = _parse_slot(raw_slot)
        if canonical in seen:
            continue
        for _, other_start, other_end in parsed:
            if _overlap(start, end, other_start, other_end):
                raise _WorkflowError("overlapping availability")
        seen.add(canonical)
        parsed.append((canonical, start, end))
    return [item[0] for item in parsed], parsed


def _normalised_configured_slot(available, requested):
    """Find a requested slot among configured slots after trimming.

    Initial state is trusted only enough to be read.  Invalid configured
    entries do not become a way around timestamp validation; they simply make
    the requested booking invalid.
    """

    if not isinstance(available, list):
        raise _WorkflowError("no availability")
    requested_canonical, requested_start, requested_end = _parse_slot(requested)
    for configured in available:
        try:
            canonical, start, end = _parse_slot(configured)
        except _WorkflowError:
            continue
        if canonical == requested_canonical:
            return canonical, requested_start, requested_end
    raise _WorkflowError("slot is not configured")


def _booking_lookup(bookings, raw_booking_id):
    """Return a canonical id and row, allowing outer-id trimming."""

    if not _text(raw_booking_id) or not isinstance(bookings, dict):
        return None, None
    wanted = raw_booking_id.strip()
    try:
        exact = bookings.get(wanted)
    except (TypeError, ValueError):
        exact = None
    if isinstance(exact, dict):
        return wanted, exact
    # State created by this implementation uses the trimmed key.  The loop
    # also makes older hand-written state with a padded key unambiguous.
    for key, value in bookings.items():
        if isinstance(key, str) and key.strip() == wanted and isinstance(value, dict):
            return key, value
    return wanted, None


def _booking_id_exists(bookings, booking_id):
    if not isinstance(bookings, dict):
        return True
    for key in bookings:
        if isinstance(key, str) and key.strip() == booking_id:
            return True
    return False


def _can_view(state, viewer_id, student_id, booking):
    viewer = _user(state, viewer_id)
    if viewer is None or not isinstance(booking, dict):
        return False
    role = viewer.get("role")
    if _is_admin(viewer):
        return True
    if role == "student":
        return viewer_id == student_id
    if role == "parent":
        children = viewer.get("student_ids")
        return isinstance(children, list) and student_id in children
    if role == "instructor":
        return booking.get("instructor_id") == viewer_id
    return False


def _valid_join_url(value):
    if not isinstance(value, str) or not value.strip():
        return False
    candidate = value.strip()
    try:
        parts = urlsplit(candidate)
    except (TypeError, ValueError):
        return False
    return parts.scheme.lower() in {"http", "https"} and bool(parts.netloc)


def _provider_service(service):
    if service is None:
        raise _ProviderError("provider unavailable")
    return service


def _meeting_link(service, booking_id, student_id, instructor_id, slot):
    try:
        response = _provider_service(service).meeting(
            booking_id, student_id, instructor_id, slot
        )
    except Exception as exc:
        raise _ProviderError("meeting failed") from exc

    # StudioClient returns the already validated URL.  A small dict response
    # is also accepted for test doubles and validates the response contract at
    # this workflow boundary.
    if isinstance(response, str):
        link = response
    elif isinstance(response, dict):
        if response.get("booking_id") != booking_id:
            raise _ProviderError("meeting id mismatch")
        link = response.get("join_url")
    else:
        raise _ProviderError("invalid meeting response")
    if not _valid_join_url(link):
        raise _ProviderError("invalid meeting link")
    return link.strip()


def _email_ack(service, event_id, payload):
    try:
        response = _provider_service(service).email(event_id, deepcopy(payload))
    except Exception as exc:
        raise _ProviderError("email failed") from exc
    if not isinstance(response, dict):
        raise _ProviderError("invalid email response")
    if response.get("accepted") is not True or response.get("event_id") != event_id:
        raise _ProviderError("email acknowledgement mismatch")
    return response


def _payment_receipt(service, event_id):
    try:
        response = _provider_service(service).payment(event_id)
    except Exception as exc:
        raise _ProviderError("payment lookup failed") from exc
    if not isinstance(response, dict):
        raise _ProviderError("invalid payment receipt")
    return response


def _payment_record_matches(record, event_id, student_id, package_id, credits):
    if not isinstance(record, dict):
        return False
    # payment_event_id is the historical field name in the supplied state
    # shape.  event_id is accepted for states written by another adapter, but
    # no receipt fields are copied into either representation.
    recorded_event = record.get("payment_event_id", record.get("event_id", event_id))
    recorded_credits = record.get("credits")
    return (
        recorded_event == event_id
        and record.get("student_id") == student_id
        and record.get("package_id") == package_id
        and isinstance(recorded_credits, int)
        and not isinstance(recorded_credits, bool)
        and recorded_credits == credits
    )


def _base_state_copy(state):
    if not isinstance(state, dict):
        return None
    try:
        out = deepcopy(state)
    except Exception:
        return None
    # result/error are transport-like fields, not business state.  Removing
    # stale copies also prevents a previous direct invocation from affecting a
    # later action.
    out.pop("result", None)
    out.pop("error", None)
    return out


def process_music_action(state: dict, action: dict, service=None) -> dict:
    """Apply one workflow action to an immutable state snapshot.

    On success the returned dictionary contains the next private state and a
    temporary ``result`` member.  On failure it contains the unchanged copied
    state and an ``error`` member.  The HTTP adapter removes those temporary
    members before persisting or replying.
    """

    out = _base_state_copy(state)
    if out is None:
        return {"error": {"code": "invalid_state"}}
    try:
        request = deepcopy(action) if isinstance(action, dict) else {}
    except Exception:
        request = {}

    for name, shape in ROOT_TYPES.items():
        if name not in out:
            out[name] = shape()
        elif not isinstance(out[name], shape):
            return _fail(out, "invalid_state")

    kind = request.get("type")

    if kind == "set_availability":
        actor_id = request.get("actor_id")
        instructor_id = request.get("instructor_id")
        actor = _user(out, actor_id)
        instructor = _user(out, instructor_id, "instructor")
        if instructor is None or actor is None:
            return _fail(out, "availability_denied")
        if not (_is_admin(actor) or actor_id == instructor_id):
            return _fail(out, "availability_denied")
        try:
            normalised, parsed = _normalise_slots(request.get("slots"))
        except _WorkflowError:
            return _fail(out, "invalid_availability")
        # ``parsed`` is intentionally computed above even though the canonical
        # list is what is persisted: it ensures every timestamp has been
        # validated before changing anything.
        del parsed
        out["availability"][instructor_id] = normalised
        out["result"] = {"slots": deepcopy(normalised)}

    elif kind == "purchase_package":
        actor_id = request.get("actor_id")
        student_id = request.get("student_id")
        actor = _user(out, actor_id)
        student = _user(out, student_id, "student")
        if actor is None or student is None:
            return _fail(out, "payment_denied")
        linked_parent = (
            actor.get("role") == "parent"
            and isinstance(actor.get("student_ids"), list)
            and student_id in actor.get("student_ids")
        )
        if not (
            _is_admin(actor)
            or (actor.get("role") == "student" and actor_id == student_id)
            or linked_parent
        ):
            # This check intentionally occurs before looking up the receipt.
            return _fail(out, "payment_denied")

        event_id = request.get("payment_event_id")
        if not _text(event_id):
            return _fail(out, "payment_denied")
        event_id = event_id.strip()

        balance = _safe_get(out["credits"], student_id, 0)
        if not _nonnegative_int(balance):
            return _fail(out, "invalid_credit_balance")
        try:
            receipt = _payment_receipt(service, event_id)
        except _ProviderError:
            return _fail(out, "payment_failed")

        if (
            receipt.get("event_id") != event_id
            or receipt.get("student_id") != student_id
            or receipt.get("paid") is not True
        ):
            return _fail(out, "payment_denied")
        package_id = receipt.get("package_id")
        if not _text(package_id):
            return _fail(out, "payment_denied")
        package_id = package_id.strip()
        if "package_id" in request and request.get("package_id") is not None:
            requested_package = request.get("package_id")
            if not _text(requested_package) or requested_package.strip() != package_id:
                return _fail(out, "payment_conflict")
        package_credits = _safe_get(out["packages"], package_id)
        if not _positive_int(package_credits):
            return _fail(out, "unknown_package")

        has_previous = event_id in out["processed_payments"]
        previous = _safe_get(out["processed_payments"], event_id)
        if has_previous:
            # A replay is still provider-checked above.  It is idempotent only
            # when all verified identity and derived-credit fields agree.
            if not _payment_record_matches(
                previous, event_id, student_id, package_id, package_credits
            ):
                return _fail(out, "payment_conflict")
            out["result"] = {
                "balance": balance,
                "duplicate": True,
                "credits": package_credits,
            }
        else:
            record = {
                "event_id": event_id,
                "student_id": student_id,
                "package_id": package_id,
                "credits": package_credits,
            }
            out["processed_payments"][event_id] = record
            out["credits"][student_id] = balance + package_credits
            out["ledger"].append(
                {
                    "event_id": event_id,
                    "student_id": student_id,
                    "delta": package_credits,
                    "reason": "package_purchase",
                    "package_id": package_id,
                }
            )
            out["result"] = {
                "balance": balance + package_credits,
                "duplicate": False,
                "credits": package_credits,
            }

    elif kind == "book":
        actor_id = request.get("actor_id")
        student_id = request.get("student_id")
        actor = _user(out, actor_id)
        student = _user(out, student_id, "student")
        parent_children = actor.get("student_ids") if isinstance(actor, dict) else None
        allowed = actor is not None and (
            (actor.get("role") == "student" and actor_id == student_id)
            or (
                actor.get("role") == "parent"
                and isinstance(parent_children, list)
                and student_id in parent_children
            )
        )
        instructor_id = request.get("instructor_id")
        instructor = _user(out, instructor_id, "instructor")
        if not allowed or student is None or instructor is None:
            return _fail(out, "booking_denied")

        booking_id = request.get("booking_id")
        if not _text(booking_id):
            return _fail(out, "booking_denied")
        booking_id = booking_id.strip()
        if _booking_id_exists(out["bookings"], booking_id):
            return _fail(out, "booking_conflict")

        try:
            available_slot, slot_start, slot_end = _normalised_configured_slot(
                _safe_get(out["availability"], instructor_id), request.get("slot")
            )
        except _WorkflowError:
            return _fail(out, "booking_denied")

        balance = _safe_get(out["credits"], student_id, 0)
        if not _nonnegative_int(balance) or balance < 1:
            return _fail(out, "booking_denied")

        # Every non-cancelled booking occupies its interval, including a
        # completed lesson.  Invalid existing intervals are treated as a
        # conservative conflict rather than being silently ignored.
        for existing in out["bookings"].values():
            if not isinstance(existing, dict):
                return _fail(out, "invalid_state")
            if existing.get("status") == "cancelled":
                continue
            if existing.get("instructor_id") != instructor_id:
                continue
            try:
                _, existing_start, existing_end = _parse_slot(existing.get("slot"))
            except _WorkflowError:
                return _fail(out, "invalid_state")
            if _overlap(slot_start, slot_end, existing_start, existing_end):
                return _fail(out, "booking_conflict")

        # All authorization, availability, credit, and overlap checks happen
        # before either provider side effect.
        try:
            link = _meeting_link(
                service, booking_id, student_id, instructor_id, available_slot
            )
            confirmation_id = f"confirmation:{booking_id}"
            confirmation_payload = {
                "event_id": confirmation_id,
                "kind": "booking_confirmation",
                "booking_id": booking_id,
                "student_id": student_id,
                "meeting_link": link,
            }
            _email_ack(service, confirmation_id, confirmation_payload)
        except _ProviderError:
            return _fail(out, "booking_provider_failed")

        out["bookings"][booking_id] = {
            "student_id": student_id,
            "instructor_id": instructor_id,
            "slot": available_slot,
            "status": "booked",
            "meeting_link": link,
            "credit_deducted": False,
        }
        out["emails"].append(
            {
                "event_id": confirmation_id,
                "kind": "booking_confirmation",
                "booking_id": booking_id,
                "student_id": student_id,
                "meeting_link": link,
            }
        )
        out["result"] = {"booking_id": booking_id, "meeting_link": link}

    elif kind == "complete":
        booking_key, booking = _booking_lookup(
            out["bookings"], request.get("booking_id")
        )
        actor_id = request.get("actor_id")
        actor = _user(out, actor_id)
        if (
            booking is None
            or actor is None
            or not (
                _is_admin(actor)
                or (
                    actor.get("role") == "instructor"
                    and actor_id == booking.get("instructor_id")
                )
            )
            or booking.get("status") not in {"booked", "completed"}
        ):
            return _fail(out, "completion_denied")

        student_id = booking.get("student_id")
        # A completed row is an idempotent read for an authorized viewer.  It
        # deliberately does not validate threshold or contact the provider.
        if booking.get("status") == "completed":
            balance = _safe_get(out["credits"], student_id, 0)
            if not _nonnegative_int(balance):
                return _fail(out, "invalid_credit_balance")
            out["result"] = {
                "status": "completed",
                "balance": balance,
                "duplicate": True,
            }
        elif booking.get("credit_deducted") is True:
            # A crash-safe state may have recorded the debit before the final
            # status write.  Never debit it a second time; the flag means the
            # provider acknowledgement and ledger work already happened.
            balance = _safe_get(out["credits"], student_id, 0)
            if not _nonnegative_int(balance):
                return _fail(out, "invalid_credit_balance")
            booking["status"] = "completed"
            out["result"] = {
                "status": "completed",
                "balance": balance,
                "duplicate": True,
            }
        else:
            balance = _safe_get(out["credits"], student_id, 0)
            if not _nonnegative_int(balance) or balance < 1:
                return _fail(out, "no_credit")
            threshold = out.get("low_credit_threshold", 1)
            if not _nonnegative_int(threshold):
                return _fail(out, "invalid_threshold")
            new_balance = balance - 1
            completion_id = f"complete:{booking_key}"

            if new_balance <= threshold:
                low_event_id = f"low_credit:{booking_key}"
                low_payload = {
                    "event_id": low_event_id,
                    "kind": "low_credit",
                    "student_id": student_id,
                    "balance": new_balance,
                    "booking_id": booking_key,
                }
                try:
                    _email_ack(service, low_event_id, low_payload)
                except _ProviderError:
                    # Nothing below this point has been changed, so a retry
                    # can safely use the same deterministic idempotency key.
                    return _fail(out, "completion_provider_failed")

                out["emails"].append(
                    {
                        "event_id": low_event_id,
                        "kind": "low_credit",
                        "student_id": student_id,
                        "balance": new_balance,
                        "booking_id": booking_key,
                    }
                )

            out["credits"][student_id] = new_balance
            booking["credit_deducted"] = True
            booking["status"] = "completed"
            out["ledger"].append(
                {
                    "event_id": completion_id,
                    "student_id": student_id,
                    "delta": -1,
                    "reason": "lesson_completed",
                }
            )
            out["result"] = {
                "status": "completed",
                "balance": new_balance,
                "duplicate": False,
            }

    elif kind == "portal":
        booking_key, booking = _booking_lookup(
            out["bookings"], request.get("booking_id")
        )
        student_id = request.get("student_id")
        viewer_id = request.get("viewer_id")
        if (
            booking is None
            or booking.get("student_id") != student_id
            or not _can_view(out, viewer_id, student_id, booking)
        ):
            return _fail(out, "portal_denied")
        balance = _safe_get(out["credits"], student_id, 0)
        if not _nonnegative_int(balance):
            return _fail(out, "invalid_credit_balance")
        viewer = _user(out, viewer_id)
        if viewer is not None and (_is_admin(viewer) or viewer.get("role") == "instructor"):
            out["audit"].append(
                {
                    "viewer_id": viewer_id,
                    "student_id": student_id,
                    "booking_id": booking_key,
                }
            )
        out["result"] = {
            "booking_id": booking_key,
            "status": booking.get("status"),
            "meeting_link": booking.get("meeting_link"),
            "credit_balance": balance,
        }

    elif kind == "cancel":
        booking_key, booking = _booking_lookup(
            out["bookings"], request.get("booking_id")
        )
        actor_id = request.get("actor_id")
        if (
            booking is None
            or booking.get("status") != "booked"
            or not _can_view(out, actor_id, booking.get("student_id"), booking)
        ):
            return _fail(out, "cancel_denied")
        booking["status"] = "cancelled"
        out["result"] = {"booking_id": booking_key, "status": "cancelled"}

    else:
        return _fail(out, "unknown_action")

    out.pop("error", None)
    return out

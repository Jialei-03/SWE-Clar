"""Music-studio starter with incomplete payment and meeting workflows."""

from copy import deepcopy


ROOT_TYPES = {
    "users": dict,
    "availability": dict,
    "bookings": dict,
    "credits": dict,
    "processed_payments": dict,
    "ledger": list,
    "emails": list,
    "audit": list,
}


def _fail(out, code):
    out["error"] = {"code": code}
    return out


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _user(out, user_id, role=None):
    value = out["users"].get(user_id)
    return value if isinstance(value, dict) and (role is None or value.get("role") == role) else None


def _can_view(out, viewer_id, student_id, booking):
    viewer = _user(out, viewer_id)
    if viewer is None or not isinstance(booking, dict):
        return False
    if viewer.get("role") == "admin" or (viewer_id == student_id and viewer.get("role") == "student"):
        return True
    children = viewer.get("student_ids")
    if viewer.get("role") == "parent" and isinstance(children, list) and student_id in children:
        return True
    return viewer.get("role") == "instructor" and booking.get("instructor_id") == viewer_id


def process_music_action(state: dict, action: dict, service=None) -> dict:
    out = deepcopy(state) if isinstance(state, dict) else {}
    request = deepcopy(action) if isinstance(action, dict) else {}
    for name, shape in ROOT_TYPES.items():
        out.setdefault(name, shape())
    if any(not isinstance(out[name], shape) for name, shape in ROOT_TYPES.items()):
        return _fail(out, "invalid_state")

    kind = request.get("type")
    if kind == "set_availability":
        actor_id, instructor_id = request.get("actor_id"), request.get("instructor_id")
        actor, instructor, slots = _user(out, actor_id), _user(out, instructor_id, "instructor"), request.get("slots")
        if actor is None or instructor is None or not (actor.get("role") == "admin" or actor_id == instructor_id) or not isinstance(slots, list) or any(not _text(slot) for slot in slots):
            return _fail(out, "availability_denied")
        out["availability"][instructor_id] = list(dict.fromkeys(slot.strip() for slot in slots))
        out["result"] = {"slots": deepcopy(out["availability"][instructor_id])}

    elif kind == "purchase_package":
        student_id = request.get("student_id")
        event_id = request.get("payment_event_id")
        amount = request.get("credits")
        if _user(out, student_id, "student") is None or not _text(event_id) or not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0 or request.get("paid") is not True:
            return _fail(out, "payment_denied")
        balance = out["credits"].get(student_id, 0)
        if not isinstance(balance, int) or isinstance(balance, bool) or balance < 0:
            return _fail(out, "invalid_credit_balance")
        row = {"payment_event_id": event_id.strip(), "student_id": student_id, "credits": amount, "paid": True}
        previous = out["processed_payments"].get(row["payment_event_id"])
        if previous is not None and previous != row:
            return _fail(out, "payment_conflict")
        if previous is None:
            out["processed_payments"][row["payment_event_id"]] = deepcopy(row)
            out["credits"][student_id] = balance + amount
            out["ledger"].append({"event_id": row["payment_event_id"], "student_id": student_id, "delta": amount, "reason": "package_purchase"})
        out["result"] = {"balance": out["credits"].get(student_id, balance), "duplicate": previous is not None}

    elif kind == "book":
        actor_id, student_id = request.get("actor_id"), request.get("student_id")
        actor, student = _user(out, actor_id), _user(out, student_id, "student")
        parent_children = actor.get("student_ids") if isinstance(actor, dict) else None
        allowed = actor is not None and (
            (actor_id == student_id and actor.get("role") == "student")
            or (actor.get("role") == "parent" and isinstance(parent_children, list) and student_id in parent_children)
        )
        instructor_id, slot, booking_id = request.get("instructor_id"), request.get("slot"), request.get("booking_id")
        available = out["availability"].get(instructor_id)
        balance = out["credits"].get(student_id, 0)
        occupied = any(isinstance(booking, dict) and booking.get("instructor_id") == instructor_id and booking.get("slot") == slot and booking.get("status") != "cancelled" for booking in out["bookings"].values())
        if not allowed or student is None or _user(out, instructor_id, "instructor") is None or not isinstance(available, list) or not _text(slot) or slot not in available or not _text(booking_id) or booking_id.strip() in out["bookings"] or occupied or not isinstance(balance, int) or isinstance(balance, bool) or balance < 1:
            return _fail(out, "booking_denied")
        bid = booking_id.strip()
        link = f"zoom://lesson/{bid}"
        out["bookings"][bid] = {"student_id": student_id, "instructor_id": instructor_id, "slot": slot, "status": "booked", "meeting_link": link, "credit_deducted": False}
        out["emails"].append({"kind": "booking_confirmation", "booking_id": bid, "student_id": student_id, "meeting_link": link})
        out["result"] = {"booking_id": bid, "meeting_link": link}

    elif kind == "complete":
        booking_id = request.get("booking_id")
        booking = out["bookings"].get(booking_id)
        actor = _user(out, request.get("actor_id"))
        if not isinstance(booking, dict) or actor is None or not (actor.get("role") == "admin" or request.get("actor_id") == booking.get("instructor_id")) or booking.get("status") not in {"booked", "completed"}:
            return _fail(out, "completion_denied")
        if booking.get("credit_deducted") is not True:
            student_id = booking.get("student_id")
            balance = out["credits"].get(student_id, 0)
            threshold = out.get("low_credit_threshold", 1)
            if not isinstance(balance, int) or isinstance(balance, bool) or balance < 1:
                return _fail(out, "no_credit")
            if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 0:
                return _fail(out, "invalid_threshold")
            out["credits"][student_id] = balance - 1
            booking["credit_deducted"] = True
            out["ledger"].append({"event_id": f"complete:{booking_id}", "student_id": student_id, "delta": -1, "reason": "lesson_completed"})
            if out["credits"][student_id] <= threshold:
                out["emails"].append({"kind": "low_credit", "student_id": student_id, "balance": out["credits"][student_id], "booking_id": booking_id})
        booking["status"] = "completed"
        out["result"] = {"status": "completed", "balance": out["credits"].get(booking.get("student_id"), 0)}

    elif kind == "portal":
        booking_id, student_id = request.get("booking_id"), request.get("student_id")
        booking = out["bookings"].get(booking_id)
        viewer_id = request.get("viewer_id")
        if not isinstance(booking, dict) or booking.get("student_id") != student_id or not _can_view(out, viewer_id, student_id, booking):
            return _fail(out, "portal_denied")
        viewer = _user(out, viewer_id)
        if viewer.get("role") in {"admin", "instructor"}:
            out["audit"].append({"viewer_id": viewer_id, "student_id": student_id, "booking_id": booking_id})
        out["result"] = {"booking_id": booking_id, "status": booking.get("status"), "meeting_link": booking.get("meeting_link"), "credit_balance": out["credits"].get(student_id, 0)}

    elif kind == "cancel":
        booking = out["bookings"].get(request.get("booking_id"))
        actor_id = request.get("actor_id")
        if not isinstance(booking, dict) or booking.get("status") != "booked" or not _can_view(out, actor_id, booking.get("student_id"), booking):
            return _fail(out, "cancel_denied")
        booking["status"] = "cancelled"
        out["result"] = {"status": "cancelled"}

    else:
        return _fail(out, "unknown_action")

    out.pop("error", None)
    return out

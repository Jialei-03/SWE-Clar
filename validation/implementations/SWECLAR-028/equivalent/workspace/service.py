"""Business logic for signups and the scheduled scheduling automation."""

from datetime import datetime, time, timedelta
import json
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from store import connect


class DeliveryUnavailable(RuntimeError):
    """Raised when the prepared local notification endpoint did not deliver."""


# ---------------------------------------------------------------------------
# Validation and formatting helpers


def _send_participant_notifications(
    db_path,
    sink_url,
    operation_key,
    subject,
    worker,
    shift,
    body,
    include_manager=False,
):
    """Send the channels belonging to a signup operation in stable order.

    Signup confirmations and employee reminders intentionally share the same
    channel ordering and recipient lookup.  Keeping that lookup here makes it
    harder for one workflow to accidentally use request data instead of the
    employee or shift that is actually linked in SQLite.  ``operation_key``
    is the prefix of each durable delivery key; the suffix remains the channel
    name so retries retain the existing idempotency contract.
    """
    recipients = [
        ("sms", worker["phone"]),
        ("email", worker["email"]),
    ]
    if include_manager:
        recipients.append(("manager_email", shift["manager_email"]))

    for channel, recipient in recipients:
        deliver(
            db_path,
            sink_url,
            f"{operation_key}:{channel}",
            subject,
            channel,
            recipient,
            body,
        )


def _required_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid_" + field)
    return value


def _parse_aware_timestamp(value, field="timestamp"):
    """Parse an ISO timestamp and require an explicit UTC offset."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid_" + field)
    text = value.strip()
    # datetime.fromisoformat accepts offsets but Python versions differ in
    # their handling of the common ISO ``Z`` spelling.
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_" + field) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("offset_required_" + field)
    return parsed


def _configured_zone(name):
    if not isinstance(name, str) or not name:
        raise ValueError("invalid_timezone")
    try:
        return ZoneInfo(name)
    except Exception as exc:  # ZoneInfoNotFoundError varies by Python version.
        raise ValueError("invalid_timezone") from exc


def _signup_body(worker, shift, label=None):
    prefix = (label + "\n") if label else ""
    # Keep the stored offset-aware timestamp verbatim.  Besides preserving the
    # customer's displayed time, this makes the offset visible in every
    # ordinary signup/reminder notification.
    return (
        f"{prefix}Worker: {worker['name']}\n"
        f"Shift starts: {shift['starts_at']}\n"
        f"Location: {shift['location']}\n"
        f"Address: {shift['address']}\n"
        f"Map: {shift['map_url']}"
    )


def _message_url(sink_url):
    if not isinstance(sink_url, str) or not sink_url.strip():
        raise DeliveryUnavailable("notification_endpoint_unavailable")
    return sink_url.rstrip("/") + "/messages"


def _post_message(sink_url, message):
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    request = Request(
        _message_url(sink_url),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=3) as response:
            status = response.getcode()
            if status != 200:
                raise DeliveryUnavailable("delivery_failed")
    except DeliveryUnavailable:
        raise
    except (URLError, TimeoutError, OSError) as exc:
        # HTTPError is a URLError, so non-200 responses (including a
        # deliberate transient 503) are reported to the HTTP caller as a
        # delivery failure too.
        raise DeliveryUnavailable("delivery_unavailable") from exc


def deliver(db_path, sink_url, key, subject, channel, recipient, body):
    """Deliver one idempotent message and durably record its success.

    The short SQLite write transaction is held while the local endpoint is
    called.  This serializes two concurrent requests attempting the same
    stable key: one sends it, and the other observes the completed delivery.
    If the endpoint fails, the transaction rolls back and a later retry can
    try the same key again.
    """
    key = _required_text(key, "delivery_id")
    subject = _required_text(subject, "delivery_subject")
    channel = _required_text(channel, "channel")
    recipient = _required_text(recipient, "recipient")
    if not isinstance(body, str):
        raise ValueError("invalid_body")

    with connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT id FROM deliveries WHERE id=?", (key,)
        ).fetchone()
        if existing:
            # A local receipt is authoritative.  In particular, daily reports
            # must not be sent a second time merely because their calculated
            # counts changed later in the day.
            return

        _post_message(
            sink_url,
            {
                "id": key,
                "channel": channel,
                "recipient": recipient,
                "body": body,
            },
        )
        db.execute(
            "INSERT INTO deliveries(id,signup_id,channel,recipient,body) "
            "VALUES(?,?,?,?,?)",
            (key, subject, channel, recipient, body),
        )


# ---------------------------------------------------------------------------
# Signup workflow


def _validate_signup_event(event):
    if not isinstance(event, dict):
        raise ValueError("invalid_request")
    signup_id = _required_text(event.get("id"), "signup_id")
    shift_id = _required_text(event.get("shift_id"), "shift_id")
    employee = event.get("employee")
    if not isinstance(employee, dict):
        raise ValueError("invalid_employee")
    employee_id = _required_text(employee.get("id"), "employee_id")
    name = _required_text(employee.get("name"), "employee_name")
    email = _required_text(employee.get("email"), "employee_email")
    phone = _required_text(employee.get("phone"), "employee_phone")
    return signup_id, shift_id, {
        "id": employee_id,
        "name": name,
        "email": email,
        "phone": phone,
    }


def _resolve_employee(db, supplied):
    """Resolve an employee by email, returning its persisted id.

    The caller owns the surrounding transaction.  An employee ID collision
    with a different email is rejected rather than silently changing identity.
    """
    by_email = db.execute(
        "SELECT * FROM employees WHERE email=?", (supplied["email"],)
    ).fetchone()
    if by_email:
        return by_email["id"]

    by_id = db.execute(
        "SELECT * FROM employees WHERE id=?", (supplied["id"],)
    ).fetchone()
    if by_id:
        # Since the email lookup above missed, this ID belongs to another
        # email and cannot be reused for a new identity.
        raise ValueError("employee_conflict")

    db.execute(
        "INSERT INTO employees(id,name,email,phone) VALUES(?,?,?,?)",
        (supplied["id"], supplied["name"], supplied["email"], supplied["phone"]),
    )
    return supplied["id"]


def _signup_details(db_path, signup_id):
    with connect(db_path) as db:
        row = db.execute(
            """
            SELECT g.*, e.name AS employee_name, e.email AS employee_email,
                   e.phone AS employee_phone,
                   s.starts_at, s.location, s.address, s.map_url,
                   s.manager_email, s.capacity, s.status AS shift_status
            FROM signups AS g
            JOIN employees AS e ON e.id=g.employee_id
            JOIN shifts AS s ON s.id=g.shift_id
            WHERE g.id=?
            """,
            (signup_id,),
        ).fetchone()
        return dict(row) if row else None


def signup(db_path, sink_url, event):
    """Create or retry a signup and its three signup notifications."""
    signup_id, shift_id, supplied_employee = _validate_signup_event(event)

    # Persist the connected records before attempting network delivery.  This
    # deliberately leaves a New signup behind when a delivery is unavailable,
    # allowing the exact request to be retried without losing the linkage.
    with connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        shift_row = db.execute(
            "SELECT * FROM shifts WHERE id=?", (shift_id,)
        ).fetchone()
        if not shift_row:
            raise ValueError("unknown_shift")
        shift = dict(shift_row)
        _parse_aware_timestamp(shift["starts_at"], "shift_starts_at")

        current = db.execute(
            "SELECT * FROM signups WHERE id=?", (signup_id,)
        ).fetchone()

        if current:
            # Resolve the submitted email without creating anything.  A
            # repeated request must point at the exact persisted employee and
            # shift; its later reminder state is never reset.
            by_email = db.execute(
                "SELECT id FROM employees WHERE email=?",
                (supplied_employee["email"],),
            ).fetchone()
            if by_email:
                resolved_employee_id = by_email["id"]
            else:
                by_id = db.execute(
                    "SELECT id FROM employees WHERE id=?",
                    (supplied_employee["id"],),
                ).fetchone()
                if by_id:
                    raise ValueError("employee_conflict")
                # This would be a new employee, and therefore cannot be the
                # employee linked by the existing signup.
                resolved_employee_id = supplied_employee["id"]

            if (
                current["employee_id"] != resolved_employee_id
                or current["shift_id"] != shift_id
            ):
                raise ValueError("signup_conflict")
            employee_id = current["employee_id"]
        else:
            employee_id = _resolve_employee(db, supplied_employee)
            other_pair = db.execute(
                "SELECT id FROM signups WHERE employee_id=? AND shift_id=?",
                (employee_id, shift_id),
            ).fetchone()
            if other_pair and other_pair["id"] != signup_id:
                raise ValueError("signup_conflict")
            db.execute(
                "INSERT INTO signups(id,employee_id,shift_id,status,checked_in) "
                "VALUES(?,?,?,'New',0)",
                (signup_id, employee_id, shift_id),
            )

        worker_row = db.execute(
            "SELECT * FROM employees WHERE id=?", (employee_id,)
        ).fetchone()
        if not worker_row:
            raise ValueError("invalid_employee")
        worker = dict(worker_row)

    body = _signup_body(worker, shift)
    _send_participant_notifications(
        db_path,
        sink_url,
        f"signup:{signup_id}",
        signup_id,
        worker,
        shift,
        body,
        include_manager=True,
    )

    # Only a New signup is promoted here.  Retrying an already-reminded signup
    # must not move it backwards to Confirmed.
    with connect(db_path) as db:
        db.execute(
            "UPDATE signups SET status='Confirmed' "
            "WHERE id=? AND status='New'",
            (signup_id,),
        )
        row = db.execute(
            "SELECT * FROM signups WHERE id=?", (signup_id,)
        ).fetchone()
        if not row:
            raise ValueError("unknown_signup")
        return dict(row)


# ---------------------------------------------------------------------------
# Scheduled automation


def _eligible_signup_ids(db_path, expected_status, predicate):
    with connect(db_path) as db:
        rows = db.execute(
            """
            SELECT g.id, s.starts_at
            FROM signups AS g
            JOIN shifts AS s ON s.id=g.shift_id
            WHERE g.status=?
            ORDER BY g.id
            """,
            (expected_status,),
        ).fetchall()
    selected = []
    for row in rows:
        starts = _parse_aware_timestamp(row["starts_at"], "shift_starts_at")
        if predicate(starts):
            selected.append(row["id"])
    return selected


def _send_employee_reminder(db_path, sink_url, signup_id, label, key_prefix):
    details = _signup_details(db_path, signup_id)
    if not details:
        return
    worker = {
        "name": details["employee_name"],
        "email": details["employee_email"],
        "phone": details["employee_phone"],
    }
    shift = {
        "starts_at": details["starts_at"],
        "location": details["location"],
        "address": details["address"],
        "map_url": details["map_url"],
    }
    body = _signup_body(worker, shift, label)
    _send_participant_notifications(
        db_path,
        sink_url,
        f"{key_prefix}:{signup_id}",
        signup_id,
        worker,
        shift,
        body,
    )


def _advance_signup(db_path, signup_id, old_status, new_status):
    with connect(db_path) as db:
        db.execute(
            "UPDATE signups SET status=? WHERE id=? AND status=?",
            (new_status, signup_id, old_status),
        )


def _shift_roster_rows(db_path):
    with connect(db_path) as db:
        rows = db.execute(
            """
            SELECT s.*, COUNT(g.id) AS filled
            FROM shifts AS s
            LEFT JOIN signups AS g ON g.shift_id=s.id
            GROUP BY s.id
            ORDER BY s.id
            """
        ).fetchall()
        return [dict(row) for row in rows]


def _report_record(shift):
    total = int(shift["capacity"])
    filled = int(shift["filled"])
    return {
        "shift_id": shift["id"],
        "starts_at": shift["starts_at"],
        "location": shift["location"],
        "total": total,
        "filled": filled,
        "remaining": total - filled,
    }


def _structured_report_body(report):
    """Encode a report canonically without changing its JSON data model.

    The delivery contract treats object-key order and whitespace as transport
    details.  Sorting keys gives retries and independent managers a stable,
    easy-to-compare representation while retaining exactly the specified
    fields and values.
    """
    return json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _process_rosters(db_path, sink_url, rows, now_local, zone):
    if now_local.time() < time(6, 0):
        return 0, []

    today = now_local.date()
    by_manager = {}
    for row in rows:
        starts = _parse_aware_timestamp(row["starts_at"], "shift_starts_at")
        if starts.astimezone(zone).date() != today:
            continue
        manager = _required_text(row["manager_email"], "manager_email")
        by_manager.setdefault(manager, []).append(_report_record(row))

    failures = []
    completed = 0
    for manager in sorted(by_manager):
        records = sorted(
            by_manager[manager], key=lambda record: record["shift_id"]
        )
        body = _structured_report_body(records)
        key = f"roster:{today.isoformat()}:{manager}"
        try:
            deliver(
                db_path,
                sink_url,
                key,
                key,
                "manager_email",
                manager,
                body,
            )
            completed += 1
        except DeliveryUnavailable as exc:
            failures.append(exc)
    return completed, failures


def _process_full_alerts(db_path, sink_url, rows):
    completed = 0
    failures = []
    for row in rows:
        if row["status"] != "Open":
            continue
        record = _report_record(row)
        if record["remaining"] > 0:
            continue
        manager = _required_text(row["manager_email"], "manager_email")
        body = _structured_report_body(record)
        key = f"full:{row['id']}"
        try:
            deliver(
                db_path,
                sink_url,
                key,
                key,
                "manager_email",
                manager,
                body,
            )
            with connect(db_path) as db:
                db.execute(
                    "UPDATE shifts SET status='Full' WHERE id=? AND status='Open'",
                    (row["id"],),
                )
            completed += 1
        except DeliveryUnavailable as exc:
            # A failed email must leave the shift Open, so a later tick can
            # retry the same stable key.
            failures.append(exc)
    return completed, failures


def tick(db_path, sink_url, now, timezone="UTC"):
    """Run all due reminder, roster, and capacity stages for an explicit now."""
    now_dt = _parse_aware_timestamp(now, "now")
    zone = _configured_zone(timezone)
    now_local = now_dt.astimezone(zone)

    failures = []
    reminders_24 = 0
    reminders_2 = 0

    next_local_date = now_local.date() + timedelta(days=1)
    ids_24 = _eligible_signup_ids(
        db_path,
        "Confirmed",
        lambda starts: (
            starts > now_dt
            and starts.astimezone(zone).date() == next_local_date
        ),
    )
    for signup_id in ids_24:
        try:
            _send_employee_reminder(
                db_path, sink_url, signup_id, "24-hour reminder", "reminder24"
            )
            _advance_signup(
                db_path, signup_id, "Confirmed", "Reminder Sent 24h"
            )
            reminders_24 += 1
        except DeliveryUnavailable as exc:
            failures.append(exc)

    ids_2 = _eligible_signup_ids(
        db_path,
        "Reminder Sent 24h",
        lambda starts: timedelta(0) < starts - now_dt <= timedelta(hours=2),
    )
    for signup_id in ids_2:
        try:
            _send_employee_reminder(
                db_path, sink_url, signup_id, "2-hour reminder", "reminder2"
            )
            _advance_signup(
                db_path, signup_id, "Reminder Sent 24h", "Reminder Sent 2h"
            )
            reminders_2 += 1
        except DeliveryUnavailable as exc:
            failures.append(exc)

    rows = _shift_roster_rows(db_path)
    rosters, roster_failures = _process_rosters(
        db_path, sink_url, rows, now_local, zone
    )
    failures.extend(roster_failures)

    full_alerts, full_failures = _process_full_alerts(db_path, sink_url, rows)
    failures.extend(full_failures)

    if failures:
        raise DeliveryUnavailable("one or more deliveries failed")

    return {
        "processed": bool(reminders_24 or reminders_2 or rosters or full_alerts),
        "reminders_24h": reminders_24,
        "reminders_2h": reminders_2,
        "rosters": rosters,
        "full_alerts": full_alerts,
    }

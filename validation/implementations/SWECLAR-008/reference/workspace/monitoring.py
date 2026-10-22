"""Household-scoped observation, rule, alert and report calculations."""
from decimal import Decimal
import hashlib
import math


RULE_KINDS = {
    "fridge_open",
    "bathroom_occupied_day",
    "bathroom_occupied_night",
    "no_occupancy",
    "exterior_open_night",
}
SEVERITIES = {"info", "warning", "critical"}
DAY_MS = 24 * 60 * 60 * 1000
MINUTE_MS = 60 * 1000


def homes(db, user):
    """Return only household IDs configured for the authenticated actor."""
    if user["role"] == "individual":
        household_id = user["household_id"]
        if household_id is None:
            return []
        exists = db.execute(
            "SELECT 1 FROM households WHERE id=?", (household_id,)
        ).fetchone()
        return [household_id] if exists else []
    if user["role"] == "caregiver":
        rows = db.execute(
            """
            SELECT a.household_id
            FROM assignments AS a
            JOIN households AS h ON h.id=a.household_id
            WHERE a.user_id=?
            ORDER BY a.household_id
            """,
            (user["id"],),
        )
        return [row["household_id"] for row in rows]
    return []


def _home_id(home):
    return home["id"] if isinstance(home, dict) or hasattr(home, "keys") else home


def snapshot(db, home, as_of):
    """Build a read-only, household-scoped current observation snapshot."""
    household_id = _home_id(home)
    freshness_ms = home["freshness_minutes"] * MINUTE_MS
    result = []
    rooms = db.execute(
        "SELECT * FROM rooms WHERE household_id=? ORDER BY id", (household_id,)
    )
    for room in rooms:
        row = {
            "household_id": household_id,
            "room_id": room["id"],
            "name": room["name"],
            "sensors": [],
        }
        sensors = db.execute(
            """
            SELECT * FROM sensors
            WHERE household_id=? AND room_id=?
            ORDER BY id
            """,
            (household_id, room["id"]),
        )
        for sensor in sensors:
            event = db.execute(
                """
                SELECT * FROM events
                WHERE household_id=? AND sensor_id=? AND timestamp_ms<=?
                ORDER BY timestamp_ms DESC, event_id DESC
                LIMIT 1
                """,
                (household_id, sensor["id"], as_of),
            ).fetchone()
            timestamp_ms = event["timestamp_ms"] if event else None
            row["sensors"].append(
                {
                    "sensor_id": sensor["id"],
                    "name": sensor["name"],
                    "kind": sensor["kind"],
                    "value": bool(event["value"]) if event else None,
                    "timestamp_ms": timestamp_ms,
                    "stale": event is None
                    or as_of - timestamp_ms > freshness_ms,
                }
            )
        result.append(row)
    return result


def saved_rules(db, home, room):
    rows = db.execute(
        """
        SELECT household_id,room_id,kind,sensor_id,enabled,threshold_minutes,severity
        FROM rules
        WHERE household_id=? AND room_id=?
        ORDER BY kind
        """,
        (home, room),
    )
    return [{**dict(row), "enabled": bool(row["enabled"])} for row in rows]


def _is_finite_number(value):
    # bool is a subclass of int, but is deliberately not a valid threshold.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def save_rule(db, user, body):
    """Validate and replace one household/room/kind rule atomically."""
    if user["role"] != "caregiver":
        return 403, "denied"

    kind = body["kind"]
    severity = body["severity"]
    threshold = body["threshold_minutes"]
    enabled = body["enabled"]
    if kind not in RULE_KINDS:
        return 400, "invalid_rule"
    if severity not in SEVERITIES:
        return 400, "invalid_rule"
    if type(enabled) is not bool:
        return 400, "invalid_rule"
    if not _is_finite_number(threshold) or not 0 <= threshold <= 1440:
        return 400, "invalid_rule"

    household_id = body["household_id"]
    room_id = body["room_id"]
    sensor_id = body["sensor_id"]
    room = db.execute(
        "SELECT 1 FROM rooms WHERE household_id=? AND id=?",
        (household_id, room_id),
    ).fetchone()
    if room is None:
        return 400, "invalid_rule"
    sensor = db.execute(
        """
        SELECT kind FROM sensors
        WHERE household_id=? AND id=? AND room_id=?
        """,
        (household_id, sensor_id, room_id),
    ).fetchone()
    if sensor is None:
        return 400, "invalid_rule"

    needs_contact = kind in {"fridge_open", "exterior_open_night"}
    needs_presence = kind in {
        "bathroom_occupied_day",
        "bathroom_occupied_night",
        "no_occupancy",
    }
    compatible = (needs_contact and sensor["kind"] == "contact") or (
        needs_presence and sensor["kind"] == "presence"
    )
    if not compatible:
        return 400, "invalid_rule"

    # The surrounding HTTP request owns the transaction.  All validation is
    # complete before this replacement, so rejection cannot alter an old rule.
    db.execute(
        """
        INSERT INTO rules
          (household_id,room_id,kind,sensor_id,enabled,threshold_minutes,severity)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(household_id,room_id,kind) DO UPDATE SET
          sensor_id=excluded.sensor_id,
          enabled=excluded.enabled,
          threshold_minutes=excluded.threshold_minutes,
          severity=excluded.severity
        """,
        (
            household_id,
            room_id,
            kind,
            sensor_id,
            1 if enabled else 0,
            threshold,
            severity,
        ),
    )
    row = db.execute(
        """
        SELECT household_id,room_id,kind,sensor_id,enabled,threshold_minutes,severity
        FROM rules WHERE household_id=? AND room_id=? AND kind=?
        """,
        (household_id, room_id, kind),
    ).fetchone()
    return 200, {**dict(row), "enabled": bool(row["enabled"])}


def _window_parts(start, end, complement=False):
    """Return sorted, non-wrapping [start,end) UTC-day windows in ms."""
    start_ms = int(start) * MINUTE_MS
    end_ms = int(end) * MINUTE_MS
    if start_ms == end_ms:
        # An equal night window is empty.  Its daytime complement is all day.
        return [(0, DAY_MS)] if complement else []
    if not complement:
        if start_ms < end_ms:
            return [(start_ms, end_ms)]
        return [(0, end_ms), (start_ms, DAY_MS)]

    # Complement of the (non-empty) night interval.
    if start_ms < end_ms:
        return [(0, start_ms), (end_ms, DAY_MS)]
    return [(end_ms, start_ms)]


def _window_for_rule(home, kind):
    if kind in {"fridge_open", "no_occupancy"}:
        return None  # None means all instants, rather than an empty window.
    night = kind in {"bathroom_occupied_night", "exterior_open_night"}
    return _window_parts(
        home["night_start"], home["night_end"], complement=not night
    )


def _window_contains(timestamp_ms, parts):
    if parts is None:
        return True
    offset = timestamp_ms % DAY_MS
    return any(start <= offset < end for start, end in parts)


def _next_window_time(timestamp_ms, parts):
    """Return the first eligible instant at or after timestamp_ms."""
    if parts is None:
        return timestamp_ms
    if not parts:
        return None
    # All application timestamps are non-negative.  floor also behaves well
    # for the fractional value produced by a fractional minute threshold.
    day = math.floor(timestamp_ms / DAY_MS)
    day_start = day * DAY_MS
    offset = timestamp_ms - day_start
    for start, end in parts:
        if offset < start:
            return day_start + start
        if start <= offset < end:
            return timestamp_ms
    return (day + 1) * DAY_MS + parts[0][0]


def _collapse_history(db, household_id, sensor_id, as_of):
    """Read a sensor history and collapse equal-timestamp ties by event ID."""
    rows = db.execute(
        """
        SELECT event_id,timestamp_ms,value
        FROM events
        WHERE household_id=? AND sensor_id=? AND timestamp_ms<=?
        ORDER BY timestamp_ms ASC,event_id ASC
        """,
        (household_id, sensor_id, as_of),
    )
    collapsed = []
    for row in rows:
        item = {
            "event_id": row["event_id"],
            "timestamp_ms": row["timestamp_ms"],
            "value": bool(row["value"]),
        }
        if collapsed and collapsed[-1]["timestamp_ms"] == item["timestamp_ms"]:
            # SQL is ascending, but spelling this out keeps the policy clear if
            # the query is ever changed.
            if item["event_id"] > collapsed[-1]["event_id"]:
                collapsed[-1] = item
        else:
            collapsed.append(item)
    return collapsed


def _state_intervals(history):
    """Make [start,end) state intervals; the final interval has end=None."""
    intervals = []
    for observation in history:
        state = observation["value"]
        timestamp = observation["timestamp_ms"]
        if not intervals:
            intervals.append({"start": timestamp, "end": None, "state": state})
        elif intervals[-1]["state"] != state:
            intervals[-1]["end"] = timestamp
            intervals.append({"start": timestamp, "end": None, "state": state})
        # Same-value observations deliberately leave the onset unchanged.
    return intervals


def _duration_point(start_ms, threshold_minutes):
    """Calculate a stable millisecond value, retaining integer JSON values."""
    duration = Decimal(str(threshold_minutes)) * Decimal(MINUTE_MS)
    point = Decimal(start_ms) + duration
    if point == point.to_integral_value():
        return int(point)
    return float(point)


def _first_trigger(interval, kind, home, threshold_minutes, upper_ms):
    """Find an interval's first eligible trigger, respecting its end."""
    threshold_point = _duration_point(interval["start"], threshold_minutes)
    parts = _window_for_rule(home, kind)
    candidate = _next_window_time(threshold_point, parts)
    if candidate is None:
        return None
    end = interval["end"]
    if end is not None:
        # A state interval is closed at the transition timestamp.
        if candidate >= end:
            return None
        if candidate > upper_ms:
            return None
    else:
        # The current interval includes the as_of instant.
        if candidate > upper_ms:
            return None
    return candidate


def _required_state(kind):
    return kind != "no_occupancy"


def _alert_id(household_id, room_id, kind, sensor_id, start_ms):
    identity = "\x1f".join(
        [household_id, room_id, kind, sensor_id, str(start_ms)]
    ).encode("utf-8")
    # Keep the generated public identifier within the documented 64-character
    # alphabet while retaining ample collision resistance for synthetic data.
    return "alert_" + hashlib.sha256(identity).hexdigest()[:58]


def _explanation(rule, interval, trigger):
    state = "on" if _required_state(rule["kind"]) else "off"
    return (
        f"Sensor {rule['sensor_id']} in room {rule['room_id']} has remained "
        f"{state} since {interval['start']} and reached the "
        f"{rule['threshold_minutes']} minute {rule['kind']} threshold at {trigger}."
    )


def alerts(db, home, as_of):
    household_id = _home_id(home)
    rules = db.execute(
        """
        SELECT household_id,room_id,kind,sensor_id,enabled,threshold_minutes,severity
        FROM rules
        WHERE household_id=? AND enabled=1
        ORDER BY room_id,kind,sensor_id
        """,
        (household_id,),
    ).fetchall()
    histories = {}
    result = []
    for rule in rules:
        sensor_key = rule["sensor_id"]
        if sensor_key not in histories:
            histories[sensor_key] = _collapse_history(
                db, household_id, sensor_key, as_of
            )
        history = histories[sensor_key]
        if not history or history[-1]["value"] != _required_state(rule["kind"]):
            continue
        latest = history[-1]
        if as_of - latest["timestamp_ms"] > home["freshness_minutes"] * MINUTE_MS:
            continue

        intervals = _state_intervals(history)
        interval = intervals[-1]
        # Window eligibility is a decision about the current instant, not the
        # instant at which the threshold happened.
        parts = _window_for_rule(home, rule["kind"])
        if not _window_contains(as_of, parts):
            continue
        trigger = _first_trigger(
            interval,
            rule["kind"],
            home,
            rule["threshold_minutes"],
            as_of,
        )
        if trigger is None:
            continue
        result.append(
            {
                "household_id": household_id,
                "room_id": rule["room_id"],
                "kind": rule["kind"],
                "sensor_id": rule["sensor_id"],
                "start_ms": interval["start"],
                "trigger_ms": trigger,
                "severity": rule["severity"],
                "alert_id": _alert_id(
                    household_id,
                    rule["room_id"],
                    rule["kind"],
                    rule["sensor_id"],
                    interval["start"],
                ),
                "explanation": _explanation(rule, interval, trigger),
            }
        )
    result.sort(key=lambda row: (row["room_id"], row["kind"], row["sensor_id"], row["start_ms"]))
    return result


def report(db, home, as_of):
    household_id = _home_id(home)
    window_start = as_of - 86400000
    result = []
    history_cache = {}

    rooms = db.execute(
        "SELECT id FROM rooms WHERE household_id=? ORDER BY id", (household_id,)
    ).fetchall()
    for room in rooms:
        room_id = room["id"]
        event_rows = db.execute(
            """
            SELECT e.timestamp_ms
            FROM events AS e
            JOIN sensors AS s
              ON s.household_id=e.household_id AND s.id=e.sensor_id
            WHERE e.household_id=? AND s.room_id=?
              AND e.timestamp_ms BETWEEN ? AND ?
            """,
            (household_id, room_id, window_start, as_of),
        ).fetchall()
        sleep_parts = _window_parts(
            home["sleep_start"], home["sleep_end"], complement=False
        )
        event_count = len(event_rows)
        sleep_event_count = sum(
            1 for row in event_rows if _window_contains(row["timestamp_ms"], sleep_parts)
        )

        rules = db.execute(
            """
            SELECT household_id,room_id,kind,sensor_id,enabled,threshold_minutes,severity
            FROM rules
            WHERE household_id=? AND room_id=? AND enabled=1
            ORDER BY kind,sensor_id
            """,
            (household_id, room_id),
        ).fetchall()
        alert_count = 0
        for rule in rules:
            sensor_id = rule["sensor_id"]
            if sensor_id not in history_cache:
                history_cache[sensor_id] = _collapse_history(
                    db, household_id, sensor_id, as_of
                )
            history = history_cache[sensor_id]
            if not history:
                continue
            for interval in _state_intervals(history):
                if interval["state"] != _required_state(rule["kind"]):
                    continue
                trigger = _first_trigger(
                    interval,
                    rule["kind"],
                    home,
                    rule["threshold_minutes"],
                    as_of,
                )
                if trigger is not None and window_start <= trigger <= as_of:
                    alert_count += 1

        result.append(
            {
                "household_id": household_id,
                "room_id": room_id,
                "event_count": event_count,
                "sleep_event_count": sleep_event_count,
                "alert_count": alert_count,
            }
        )
    return {"as_of": as_of, "window_start": window_start, "rooms": result}

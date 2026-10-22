"""Deterministic policy for turning classified goal observations into events."""

import math


def _finite_number(value, name):
    """Return *value* as a finite float, rejecting non-numeric values."""
    # ``bool`` is an ``int`` subclass, but it is not a meaningful duration or
    # timestamp for this interface.
    if isinstance(value, bool) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def detect_goal_events(frames, **policy_options):
    """Return timestamps of eligible goal candidates in chronological order.

    ``frames`` is already classified by the trajectory detector.  A true
    ``goal_candidate`` is emitted immediately unless it falls strictly before
    the end of the cooldown measured from the most recently emitted event.
    False observations do not affect that last-emitted timestamp.
    """
    raw_cooldown = policy_options.get("cooldown_seconds", 5.0)
    cooldown = _finite_number(raw_cooldown, "cooldown_seconds")
    if cooldown < 0:
        raise ValueError("cooldown_seconds must be non-negative")

    events = []
    # Store the next admissible time rather than the last event.  This makes
    # the boundary rule explicit: a candidate exactly at this instant is
    # accepted, while observations before it are ignored.  The gate advances
    # only when an event is emitted, so false observations cannot extend or
    # restart a cooldown.
    next_admissible = None
    for observation in frames:
        if not observation["goal_candidate"]:
            continue

        timestamp = _finite_number(observation["timestamp"], "timestamp")
        if next_admissible is None or timestamp >= next_admissible:
            events.append(timestamp)
            next_admissible = timestamp + cooldown

    return events

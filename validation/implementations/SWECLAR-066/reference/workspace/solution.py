"""Pure state transitions for the synthetic geometry escape room.

The browser is deliberately a thin client: all of the rules that affect the
room live here as small, side-effect-free transitions.  A rejected transition
returns a copy of the supplied state with an error object; it never edits the
object passed by the caller.
"""

from __future__ import annotations

from copy import deepcopy
import math
import numbers
from typing import Any


_ALLOWED_PRESENTATIONS = {"standalone", "embedded"}
_ACTION_FIELDS = {
    "solve": {"type", "puzzle", "answer"},
    "exit": {"type"},
    "viewport": {"type", "width", "height"},
    "presentation": {"type", "mode"},
    "text": {"type", "locale", "key"},
}


def _copy_state(state: Any) -> dict:
    """Return a detached state copy suitable for a response."""
    if isinstance(state, dict):
        return deepcopy(state)
    return {}


def _reject(state: Any, code: str) -> dict:
    """Build an error response without changing gameplay fields."""
    result = _copy_state(state)
    result["error"] = {"code": code}
    return result


def _accepted_copy(state: dict) -> dict:
    result = deepcopy(state)
    # An error belongs to the previous response, not to the next successful
    # application state.  This also keeps the HTTP /state representation clean
    # after a rejected request was followed by a valid one.
    result.pop("error", None)
    return result


def _all_required_solved(state: dict) -> bool:
    """Evaluate the exit gate using membership, not counts or list lengths."""
    required = state.get("required_puzzles")
    solved = state.get("solved")
    if not isinstance(required, (list, tuple)) or not isinstance(solved, (list, tuple)):
        return False

    # A list membership check intentionally tolerates unknown and duplicate
    # entries in solved.  It also avoids requiring puzzle IDs to be hashable in
    # a malformed externally supplied state.
    return all(puzzle_id in solved for puzzle_id in required)


def _has_only_fields(action: dict, operation: str) -> bool:
    return set(action) == _ACTION_FIELDS[operation]


def _finite_positive_number(value: Any) -> float | None:
    """Convert a JSON-like number to a finite positive float.

    bool is an int subclass in Python, but it is explicitly not a valid
    viewport dimension.
    """
    if isinstance(value, bool) or not isinstance(value, numbers.Number):
        return None
    try:
        converted = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(converted) or converted <= 0:
        return None
    return converted


def _lookup_text(state: dict, locale: str, key: str) -> str:
    texts = state.get("texts")
    if isinstance(texts, dict):
        selected = texts.get(locale)
        if isinstance(selected, dict) and key in selected:
            value = selected[key]
            if isinstance(value, str):
                # In particular, do not use truthiness here: "" is a valid
                # translation and must not fall through to English.
                return value

        english = texts.get("en")
        if isinstance(english, dict) and key in english:
            value = english[key]
            if isinstance(value, str):
                return value
    return key


def apply_escape_room_action(state: dict, action: dict) -> dict:
    """Apply one public escape-room operation and return a new state.

    Supported operations are ``solve``, ``exit``, ``viewport``,
    ``presentation`` and ``text``.  Both arguments are treated as immutable;
    all successful and rejected responses are detached copies.
    """
    if not isinstance(state, dict):
        return _reject({}, "invalid_state")
    if not isinstance(action, dict):
        return _reject(state, "invalid_action")

    operation = action.get("type")
    if not isinstance(operation, str) or operation not in _ACTION_FIELDS:
        return _reject(state, "invalid_action")
    if not _has_only_fields(action, operation):
        return _reject(state, "invalid_action")

    if operation == "solve":
        puzzle_id = action.get("puzzle")
        submitted = action.get("answer")
        if not isinstance(puzzle_id, str) or not isinstance(submitted, str):
            return _reject(state, "invalid_answer")

        puzzles = state.get("puzzles")
        if not isinstance(puzzles, dict) or puzzle_id not in puzzles:
            return _reject(state, "unknown_puzzle")

        configured = puzzles[puzzle_id]
        # The supplied fixture stores each answer as {"answer": "..."};
        # accepting a direct string as well makes the public state model useful
        # for equally valid synthetic scenarios without changing its meaning.
        if isinstance(configured, dict):
            expected = configured.get("answer")
        else:
            expected = configured
        if not isinstance(expected, str):
            return _reject(state, "invalid_puzzle")
        if submitted.strip() != expected:
            return _reject(state, "wrong_answer")

        # A portrait viewport is deliberately modal in the client.  Enforcing
        # the same rule here prevents a direct request from bypassing it.
        if bool(state.get("rotate_prompt", False)):
            return _reject(state, "portrait_viewport")

        solved = state.get("solved")
        if not isinstance(solved, list):
            return _reject(state, "invalid_state")

        result = _accepted_copy(state)
        solved_copy = result["solved"]
        if puzzle_id not in solved_copy:
            solved_copy.append(puzzle_id)
        # Recalculate on every successful solve, including a repeat.  Unknown
        # or duplicate solved entries do not affect this membership-based gate.
        result["exit_open"] = _all_required_solved(result)
        return result

    if operation == "exit":
        if bool(state.get("rotate_prompt", False)):
            return _reject(state, "portrait_viewport")
        if not _all_required_solved(state):
            return _reject(state, "exit_locked")

        result = _accepted_copy(state)
        # Keep the invariant explicit even if a caller supplied a stale flag.
        result["exit_open"] = True
        result["escaped"] = True
        return result

    if operation == "viewport":
        width = _finite_positive_number(action.get("width"))
        height = _finite_positive_number(action.get("height"))
        if width is None or height is None:
            return _reject(state, "invalid_viewport")

        result = _accepted_copy(state)
        result["rotate_prompt"] = height > width
        result["aspect_supported"] = abs(width / height - (16 / 9)) <= 0.02
        return result

    if operation == "presentation":
        mode = action.get("mode")
        if not isinstance(mode, str) or mode not in _ALLOWED_PRESENTATIONS:
            return _reject(state, "invalid_presentation")
        result = _accepted_copy(state)
        result["presentation"] = mode
        return result

    # operation == "text"
    locale = action.get("locale")
    key = action.get("key")
    if not isinstance(locale, str) or not isinstance(key, str):
        return _reject(state, "invalid_text_request")
    result = _accepted_copy(state)
    result["text"] = _lookup_text(state, locale, key)
    return result

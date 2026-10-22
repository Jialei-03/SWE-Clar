"""Side-effect-free rules for the synthetic geometry escape room.

The HTTP and browser layers both use :func:`apply_escape_room_action`.  Each
operation below produces a detached response, so a rejected request can carry
an error observation without becoming part of the committed room state.
"""

from __future__ import annotations

from copy import deepcopy
import math
import numbers
from typing import Any, Callable


_ALLOWED_PRESENTATIONS = frozenset(("standalone", "embedded"))
_ACTION_FIELDS = {
    "solve": frozenset(("type", "puzzle", "answer")),
    "exit": frozenset(("type",)),
    "viewport": frozenset(("type", "width", "height")),
    "presentation": frozenset(("type", "mode")),
    "text": frozenset(("type", "locale", "key")),
}


def _clone(state: Any) -> dict:
    """Return a completely detached dictionary for a response."""
    return deepcopy(state) if isinstance(state, dict) else {}


def _rejected(state: Any, code: str) -> dict:
    response = _clone(state)
    response["error"] = {"code": code}
    return response


def _accepted(state: dict) -> dict:
    response = deepcopy(state)
    # Errors describe an earlier request.  They are intentionally not carried
    # into the next committed state or into a later successful observation.
    response.pop("error", None)
    return response


def _required_puzzles_complete(state: dict) -> bool:
    """Check requirements by membership rather than by list cardinality."""
    required = state.get("required_puzzles")
    solved = state.get("solved")
    if not isinstance(required, (list, tuple)) or not isinstance(solved, (list, tuple)):
        return False
    return all(puzzle_id in solved for puzzle_id in required)


def _exact_fields(action: dict, operation: str) -> bool:
    return set(action) == _ACTION_FIELDS[operation]


def _configured_answer(puzzles: Any, puzzle_id: str) -> str | None:
    """Read either form of the synthetic puzzle configuration.

    The supplied scenario uses ``{"answer": "..."}``, while accepting a
    direct string is useful for equivalent small synthetic scenarios.  In both
    cases the value used for comparison must itself be a string.
    """
    if not isinstance(puzzles, dict) or puzzle_id not in puzzles:
        return None
    configured = puzzles[puzzle_id]
    if isinstance(configured, dict):
        configured = configured.get("answer")
    return configured if isinstance(configured, str) else None


def _positive_finite(value: Any) -> float | None:
    """Return a usable viewport dimension, excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, numbers.Number):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _text_value(state: dict, locale: str, key: str) -> str:
    texts = state.get("texts")
    if not isinstance(texts, dict):
        return key

    # Checking membership separately from truthiness preserves an explicitly
    # translated empty string.
    localized = texts.get(locale)
    if isinstance(localized, dict) and key in localized:
        value = localized[key]
        if isinstance(value, str):
            return value

    english = texts.get("en")
    if isinstance(english, dict) and key in english:
        value = english[key]
        if isinstance(value, str):
            return value
    return key


def _solve(state: dict, action: dict) -> dict:
    puzzle_id = action.get("puzzle")
    submitted = action.get("answer")
    if not isinstance(puzzle_id, str) or not isinstance(submitted, str):
        return _rejected(state, "invalid_answer")

    puzzles = state.get("puzzles")
    if not isinstance(puzzles, dict) or puzzle_id not in puzzles:
        return _rejected(state, "unknown_puzzle")
    expected = _configured_answer(puzzles, puzzle_id)
    if expected is None:
        return _rejected(state, "invalid_puzzle")
    if submitted.strip() != expected:
        return _rejected(state, "wrong_answer")

    # The browser makes portrait mode modal.  Keeping the guard in the pure
    # transition prevents a direct HTTP call from bypassing that interaction.
    if bool(state.get("rotate_prompt", False)):
        return _rejected(state, "portrait_viewport")

    solved = state.get("solved")
    if not isinstance(solved, list):
        return _rejected(state, "invalid_state")

    response = _accepted(state)
    solved_response = response["solved"]
    if puzzle_id not in solved_response:
        solved_response.append(puzzle_id)
    response["exit_open"] = _required_puzzles_complete(response)
    return response


def _leave(state: dict) -> dict:
    if bool(state.get("rotate_prompt", False)):
        return _rejected(state, "portrait_viewport")
    if not _required_puzzles_complete(state):
        return _rejected(state, "exit_locked")

    response = _accepted(state)
    response["exit_open"] = True
    response["escaped"] = True
    return response


def _viewport(state: dict, action: dict) -> dict:
    width = _positive_finite(action.get("width"))
    height = _positive_finite(action.get("height"))
    if width is None or height is None:
        return _rejected(state, "invalid_viewport")

    response = _accepted(state)
    response["rotate_prompt"] = height > width
    response["aspect_supported"] = abs(width / height - (16 / 9)) <= 0.02
    return response


def _presentation(state: dict, action: dict) -> dict:
    mode = action.get("mode")
    if not isinstance(mode, str) or mode not in _ALLOWED_PRESENTATIONS:
        return _rejected(state, "invalid_presentation")
    response = _accepted(state)
    response["presentation"] = mode
    return response


def _text(state: dict, action: dict) -> dict:
    locale = action.get("locale")
    key = action.get("key")
    if not isinstance(locale, str) or not isinstance(key, str):
        return _rejected(state, "invalid_text_request")
    response = _accepted(state)
    response["text"] = _text_value(state, locale, key)
    return response


_HANDLERS: dict[str, Callable[[dict, dict], dict]] = {
    "solve": _solve,
    "exit": lambda state, _action: _leave(state),
    "viewport": _viewport,
    "presentation": _presentation,
    "text": _text,
}


def apply_escape_room_action(state: dict, action: dict) -> dict:
    """Apply one public room operation without mutating either argument."""
    if not isinstance(state, dict):
        return _rejected({}, "invalid_state")
    if not isinstance(action, dict):
        return _rejected(state, "invalid_action")

    operation = action.get("type")
    if not isinstance(operation, str) or operation not in _ACTION_FIELDS:
        return _rejected(state, "invalid_action")
    if not _exact_fields(action, operation):
        return _rejected(state, "invalid_action")
    return _HANDLERS[operation](state, action)

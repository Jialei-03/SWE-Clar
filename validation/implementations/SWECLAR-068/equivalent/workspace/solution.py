"""Pure evaluator for the supplied signal component.

The evaluator is intentionally a small data transformation: its only inputs
are the configuration and observations passed by the caller.  The result is
assembled from fresh containers, so evaluating a request cannot update the
request's dictionaries or any state shared by a later request.
"""

from __future__ import annotations

from typing import Any


# The local viewer uses this same boundary when deciding which menu size to
# report.  The contract specifically exercises a 390px viewport, while a
# slightly wider mobile range keeps the presentation rule useful on phones.
_MOBILE_VIEWPORT_MAX = 600

# Kept as a tuple so that each result receives a new style mapping rather than
# exposing a mutable module-level dictionary to callers.
_STYLE_PAIRS = (
    ("htf1", "green"),
    ("htf2", "red"),
    ("regression", "#ff00e7"),
)


def _json_true(value: Any) -> bool:
    """Recognize the JSON boolean true without accepting numeric truthiness."""

    return value is True


def _object_field(value: Any) -> dict:
    """Use an object-valued field or an empty object for an absent one."""

    return value if isinstance(value, dict) else {}


def _supported_trend(value: Any) -> str | None:
    """Return only the two trend observations understood by the evaluator."""

    if value == "bull" or value == "bear":
        return value
    return None


def _active_signal_names(config: dict, context: dict) -> list:
    """Select signals in state-map order using two independent controls."""

    controls = _object_field(config.get("triggers"))
    states = _object_field(context.get("trigger_states"))

    # Iterating states, rather than the configured controls, both preserves
    # the caller's order and prevents a configured-but-unobserved name from
    # becoming active.
    return [
        name
        for name, firing in states.items()
        if _json_true(firing) and _json_true(controls.get(name))
    ]


def _blackout_applies(config: dict, context: dict) -> bool:
    """Check the optional exact-string blackout without normalizing times."""

    if not _json_true(config.get("blackout_enabled")):
        return False

    times = config.get("blackout_times")
    if not isinstance(times, (list, tuple)):
        return False
    return context.get("time") in times


def _available_trends(config: dict, context: dict) -> tuple[str, ...]:
    """Return active, supported HTF observations in timeframe order."""

    trends: list[str] = []

    htf1 = _supported_trend(context.get("htf1"))
    if htf1 is not None:
        # TF1 is the primary timeframe and has no enable switch in this
        # component.
        trends.append(htf1)

    if _json_true(config.get("tf2_enabled")):
        htf2 = _supported_trend(context.get("htf2"))
        if htf2 is not None:
            trends.append(htf2)

    return tuple(trends)


def _classify(trends: tuple[str, ...]) -> str:
    """Map zero, one, or two available trends to the public grade labels."""

    if len(trends) == 2:
        return "grade_a" if trends[0] == trends[1] else "grade_b"
    if len(trends) == 1:
        return trends[0]
    return "neutral"


def _menu_size(context: dict) -> str:
    """Derive the presentation size from the supplied viewport observation."""

    width = context.get("viewport_width")
    if isinstance(width, (int, float)) and not isinstance(width, bool):
        if 0 < width <= _MOBILE_VIEWPORT_MAX:
            return "mobile"
    return "desktop"


def _styles() -> dict[str, str]:
    """Create the line-color mapping expected by the SVG adapter."""

    return dict(_STYLE_PAIRS)


def evaluate_indicator(config: dict, context: dict) -> dict:
    """Evaluate supplied observations into a deterministic JSON result.

    Signal selection, blackout handling, trend classification, and viewer
    presentation are calculated as separate pure steps.  No step writes to
    either input mapping; the only list that is cleared for a blackout is the
    fresh list returned by ``_active_signal_names``.
    """

    active_signals = _active_signal_names(config, context)
    if _blackout_applies(config, context):
        active_signals = []

    return {
        "active_signals": active_signals,
        "tf1_active": True,
        "classification": _classify(_available_trends(config, context)),
        "labels_visible": True,
        "styles": _styles(),
        "menu": {
            "visible": _json_true(config.get("menu_visible")),
            "size": _menu_size(context),
        },
    }

"""Deterministic reference implementation for the supplied signal component.

The component deliberately operates only on the observations supplied by its
caller.  It does not keep state and it never modifies either input mapping.
"""

from __future__ import annotations

from typing import Any


# The viewer uses the same breakpoint when deciding whether its information
# panel should be treated as mobile-sized.  The contract only requires the
# mobile result at a 390px viewport; 600px is a conventional small-screen
# boundary and leaves wider viewports as desktop.
_MOBILE_VIEWPORT_MAX = 600


def _is_true(value: Any) -> bool:
    """Return true only for the JSON boolean ``true``.

    The input contract describes these controls as booleans.  Being strict
    here means that an accidental value such as ``1`` cannot enable a signal
    or option merely because Python considers it truthy.
    """

    return value is True


def _trend(value: Any) -> str | None:
    """Return a supported trend observation, or ``None`` if it is unavailable."""

    if value == "bull" or value == "bear":
        return value
    return None


def _classification(config: dict, context: dict) -> str:
    """Classify the active, available higher-timeframe observations."""

    # TF1 is the primary timeframe and is always enabled by this local
    # contract.  An absent/null observation is nevertheless unavailable for
    # classification.  TF2 contributes only when explicitly selected.
    observations: list[str] = []
    htf1 = _trend(context.get("htf1"))
    if htf1 is not None:
        observations.append(htf1)

    if _is_true(config.get("tf2_enabled")):
        htf2 = _trend(context.get("htf2"))
        if htf2 is not None:
            observations.append(htf2)

    if len(observations) == 2:
        return "grade_a" if observations[0] == observations[1] else "grade_b"
    if len(observations) == 1:
        return observations[0]
    return "neutral"


def _menu_size(context: dict) -> str:
    """Choose the result's presentation size from the supplied viewport."""

    width = context.get("viewport_width")
    # viewport_width is a JSON number in the public interface.  Treat a
    # missing or malformed value as desktop rather than inventing a viewport.
    if isinstance(width, (int, float)) and not isinstance(width, bool):
        if 0 < width <= _MOBILE_VIEWPORT_MAX:
            return "mobile"
    return "desktop"


def evaluate_indicator(config: dict, context: dict) -> dict:
    """Evaluate the supplied configuration and observations.

    Trigger membership is intentionally independent: the iteration order is
    taken from ``context["trigger_states"]``, while a signal is active only
    when both its context state and its configured control are exactly true.
    All other fields are derived from the current arguments, so repeated
    calls with equal JSON inputs produce equal results.
    """

    # Valid adapter requests contain objects for these fields.  Treating a
    # missing/null object as empty keeps the function deterministic while also
    # honoring the rule that an absent trigger control cannot fire.
    configured = config.get("triggers")
    if not isinstance(configured, dict):
        configured = {}

    states = context.get("trigger_states")
    if not isinstance(states, dict):
        states = {}

    active_signals = [
        name
        for name, firing in states.items()
        if _is_true(firing) and _is_true(configured.get(name))
    ]

    # An enabled exact-time blackout suppresses the signal list only.  The
    # comparison is deliberately not parsed or normalized.
    if _is_true(config.get("blackout_enabled")):
        blackout_times = config.get("blackout_times")
        if isinstance(blackout_times, (list, tuple)) and context.get("time") in blackout_times:
            active_signals = []

    return {
        "active_signals": active_signals,
        "tf1_active": True,
        "classification": _classification(config, context),
        "labels_visible": True,
        "styles": {
            "htf1": "green",
            "htf2": "red",
            "regression": "#ff00e7",
        },
        "menu": {
            "visible": _is_true(config.get("menu_visible")),
            "size": _menu_size(context),
        },
    }

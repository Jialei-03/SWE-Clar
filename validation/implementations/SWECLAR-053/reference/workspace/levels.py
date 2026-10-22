"""Deterministic rolling price-level analysis.

The analyzer in this module deliberately works only on the bars supplied by the
caller.  It does not keep state between calls and does not use any external
services.
"""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any


_PRICE_FIELDS = ("open", "high", "low", "close")


def _as_decimal_number(value: Any, name: str) -> Decimal:
    """Return the decimal representation used for numeric comparisons.

    JSON numbers arrive here as ``int`` or ``float`` values.  Constructing a
    Decimal from ``str`` rather than from a float's binary value is important:
    for example, a distance of 0.3 must compare equal to a three-tenths tick
    buffer.  Decimal is also accepted for callers using the Python API
    directly; other objects (including strings and booleans) are not JSON
    numeric values and are rejected.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{name} must be a finite number")

    try:
        if isinstance(value, Decimal):
            result = value
        elif isinstance(value, float):
            # str gives the decimal spelling of the JSON/Python number rather
            # than exposing the float's binary implementation detail.
            result = Decimal(str(value))
        else:
            result = Decimal(value)
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        raise ValueError(f"{name} must be a finite number") from None

    if not result.is_finite():
        raise ValueError(f"{name} must be a finite number")
    return result


def _require_boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _require_integer(value: Any, name: str, *, positive: bool = False) -> int:
    # bool is an int subclass, but is not an integer option in this API.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    if not positive and value < 0:
        raise ValueError(f"{name} must be non-negative")
    return int(value)


def _parse_bars(bars: Any) -> list[dict[str, Any]]:
    """Validate bars and retain both their original and comparison values."""

    if not isinstance(bars, list):
        raise ValueError("bars must be a list of OHLC dictionaries")

    parsed: list[dict[str, Any]] = []
    for index, bar in enumerate(bars):
        if not isinstance(bar, Mapping):
            raise ValueError(f"bar {index} must be an OHLC dictionary")

        originals: dict[str, Any] = {}
        decimals: dict[str, Decimal] = {}
        for field in _PRICE_FIELDS:
            if field not in bar:
                raise ValueError(f"bar {index} is missing {field}")
            value = bar[field]
            originals[field] = value
            decimals[field] = _as_decimal_number(value, f"bar {index} {field}")

        # Validate the complete OHLC shape, not just the two values used by a
        # particular level source.  This also enforces high >= low and that
        # both open and close lie inside the wick.
        low = decimals["low"]
        high = decimals["high"]
        if low > high or not (low <= decimals["open"] <= high) or not (
            low <= decimals["close"] <= high
        ):
            raise ValueError(f"bar {index} has inconsistent OHLC prices")

        parsed.append(
            {
                "original": originals,
                "decimal": decimals,
                "high_decimal": high,
                "low_decimal": low,
            }
        )
    return parsed


def _extreme_price(
    window: list[dict[str, Any]], field: str, *, maximum: bool
) -> tuple[Any, Decimal]:
    """Select an original price and its decimal comparison value.

    The first value wins ties.  Equal numeric values are interchangeable for
    the calculation, while retaining the original value avoids needlessly
    changing the caller's numeric representation in the result.
    """

    selected = window[0]
    selected_decimal = selected["decimal"][field]
    for bar in window[1:]:
        candidate_decimal = bar["decimal"][field]
        is_better = (
            candidate_decimal > selected_decimal
            if maximum
            else candidate_decimal < selected_decimal
        )
        if is_better:
            selected = bar
            selected_decimal = candidate_decimal
    return selected["original"][field], selected_decimal


def _public_level(level: dict[str, Any]) -> dict[str, Any]:
    """Remove implementation-only comparison data from a level record."""

    return {
        "side": level["side"],
        "price": level["price"],
        "created_at": level["created_at"],
        "status": level["status"],
        "extends_to": level["extends_to"],
    }


def analyze_levels(
    bars,
    lookback,
    *,
    use_close_instead_of_wick=False,
    keep_past_levels=False,
    min_distance_ticks=0,
    tick_size=1.0,
    hide_broken_levels=True,
    extend_points=5,
    **unknown_options,
):
    """Analyze rolling high and low price levels from completed OHLC bars.

    At index ``i`` the candidate window is ``bars[i-lookback:i]``.  Existing
    levels are tested against the current bar before those candidates are
    admitted, so a level cannot break on the bar on which it is created.
    """

    if unknown_options:
        names = ", ".join(sorted(unknown_options))
        raise ValueError(f"unknown option(s): {names}")

    use_close_instead_of_wick = _require_boolean(
        use_close_instead_of_wick, "use_close_instead_of_wick"
    )
    keep_past_levels = _require_boolean(keep_past_levels, "keep_past_levels")
    hide_broken_levels = _require_boolean(hide_broken_levels, "hide_broken_levels")
    lookback = _require_integer(lookback, "lookback", positive=True)
    min_distance_ticks = _require_integer(
        min_distance_ticks, "min_distance_ticks", positive=False
    )
    extend_points = _require_integer(extend_points, "extend_points", positive=False)
    tick_size_decimal = _as_decimal_number(tick_size, "tick_size")
    if tick_size_decimal <= 0:
        raise ValueError("tick_size must be positive")

    parsed_bars = _parse_bars(bars)
    # Fraction(Decimal) retains the exact base-10 value, avoiding context
    # rounding for unusually long JSON decimals while preserving the required
    # inclusive boundary comparison.
    separation = Fraction(min_distance_ticks) * Fraction(tick_size_decimal)

    # Every internal record is kept until the end so that status transitions
    # and creation ordering are both explicit.  _price_decimal is never
    # exposed in the returned records.
    levels: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    break_events: list[dict[str, Any]] = []

    for index in range(lookback, len(parsed_bars)):
        current_bar = parsed_bars[index]

        # Breaks happen before candidate creation.  The active list is kept in
        # creation order, which also gives the required order for events at a
        # shared breaking index.
        still_active: list[dict[str, Any]] = []
        for level in active:
            if level["side"] == "high":
                is_broken = current_bar["high_decimal"] > level["price_decimal"]
            else:
                is_broken = current_bar["low_decimal"] < level["price_decimal"]

            if is_broken:
                level["status"] = "broken"
                break_events.append(
                    {
                        "side": level["side"],
                        "price": level["price"],
                        "index": index,
                    }
                )
            else:
                still_active.append(level)
        active = still_active

        window = parsed_bars[index - lookback : index]
        if use_close_instead_of_wick:
            source_field = "close"
            high_price, high_decimal = _extreme_price(
                window, source_field, maximum=True
            )
            low_price, low_decimal = _extreme_price(
                window, source_field, maximum=False
            )
        else:
            high_price, high_decimal = _extreme_price(window, "high", maximum=True)
            low_price, low_decimal = _extreme_price(window, "low", maximum=False)

        # Candidates are deliberately handled high then low.  Suppression is
        # checked against the pre-admission active set, before replacement.
        for side, price, price_decimal in (
            ("high", high_price, high_decimal),
            ("low", low_price, low_decimal),
        ):
            if min_distance_ticks > 0:
                suppressed = any(
                    level["side"] == side
                    and level["status"] == "active"
                    and abs(
                        Fraction(price_decimal) - level["price_fraction"]
                    ) <= separation
                    for level in active
                )
                if suppressed:
                    continue

            if not keep_past_levels:
                still_active = []
                for level in active:
                    if level["side"] == side:
                        level["status"] = "replaced"
                    else:
                        still_active.append(level)
                active = still_active

            new_level = {
                "side": side,
                "price": price,
                "price_decimal": price_decimal,
                "price_fraction": Fraction(price_decimal),
                "created_at": index,
                "status": "active",
                "extends_to": index + extend_points,
            }
            levels.append(new_level)
            active.append(new_level)

    active_levels = [_public_level(level) for level in active]
    display_levels = [
        _public_level(level)
        for level in levels
        if level["status"] == "active"
        or (level["status"] == "broken" and not hide_broken_levels)
    ]

    return {
        "active_levels": active_levels,
        "display_levels": display_levels,
        "break_events": break_events,
    }

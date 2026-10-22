"""Starter for the rolling price-level task."""


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
):
    return {"active_levels": [], "display_levels": [], "break_events": []}

"""Place lookup orchestration for the itinerary backend."""

import math
import numbers
from collections.abc import Mapping


_EXEMPT_TYPES = frozenset(
    {
        "neighborhood",
        "natural_feature",
        "route",
        "tourist_attraction",
        "point_of_interest",
        "park",
    }
)


def _valid_rating(value):
    """Return whether value is a finite, non-boolean number at least three."""
    if isinstance(value, bool) or not isinstance(value, numbers.Number):
        return False
    try:
        # Integral values do not need conversion through float, so arbitrarily
        # large (but still finite) Python integers remain valid numbers.
        if isinstance(value, numbers.Integral):
            return value >= 3
        return bool(math.isfinite(value) and value >= 3)
    except (TypeError, ValueError, OverflowError):
        return False


def _valid_user_rating_count(value):
    """Return whether value is a non-negative integer count of at least 50."""
    return (
        not isinstance(value, bool)
        and isinstance(value, numbers.Integral)
        and value >= 0
        and value >= 50
    )


def is_valid_place(place):
    """Return whether a normalized place satisfies the acceptance policy."""
    if not isinstance(place, Mapping):
        return False

    # Closed status is checked before the type exemptions, as required by the
    # policy.  Other statuses (including a missing status) are not restrictions.
    status = place.get("businessStatus")
    if status == "CLOSED_TEMPORARILY" or status == "CLOSED_PERMANENTLY":
        return False

    types = place.get("types")
    if not isinstance(types, list) or not all(
        isinstance(place_type, str) for place_type in types
    ):
        return False

    if any(place_type in _EXEMPT_TYPES for place_type in types):
        return True

    return _valid_rating(place.get("rating")) and _valid_user_rating_count(
        place.get("userRatingCount")
    )


def _merge_activity_and_place(activity, place):
    """Copy activity metadata and let all place metadata override collisions."""
    enriched = dict(activity)
    enriched.update(place)
    return enriched


def resolve_activity(activity, location, find_place, find_replacement):
    """Return enriched acceptable activity data, or ``None``."""
    business_name = activity["business_name"]
    description = activity["description"]

    primary = find_place(business_name, location)
    if is_valid_place(primary):
        return _merge_activity_and_place(activity, primary)

    replacement = find_replacement(description, location)
    if is_valid_place(replacement):
        return _merge_activity_and_place(activity, replacement)

    return None

"""Geographic and local-map geometry helpers.

The routing graph is deliberately small, but the calculations in this module are
kept independent of the graph provider.  In particular, route lengths use the
haversine formula while navigation's off-route check uses the local projection
specified by the component contract.
"""

import math

R = 6371008.8
METRES_PER_MILE = 1609.344


def _number(value):
    """Return *value* as a float when it is a finite, non-boolean number."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid point")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("invalid point")
    if not math.isfinite(result):
        raise ValueError("invalid point")
    return result


def point(value):
    """Validate and copy a latitude/longitude mapping.

    Only ``lat`` and ``lon`` are part of a point.  Extra fields are intentionally
    ignored so a provider's node object cannot accidentally become persisted
    workflow state.
    """

    if not isinstance(value, dict):
        raise ValueError("invalid point")
    try:
        lat = _number(value.get("lat"))
        lon = _number(value.get("lon"))
    except ValueError:
        raise ValueError("invalid point")
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise ValueError("invalid point")
    return {"lat": lat, "lon": lon}


def meters(a, b):
    """Return the haversine distance between two validated points in metres."""

    a = point(a)
    b = point(b)
    lat_a = math.radians(a["lat"])
    lat_b = math.radians(b["lat"])
    d_lat = lat_b - lat_a
    d_lon = math.radians(b["lon"] - a["lon"])
    h = (
        math.sin(d_lat / 2.0) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(d_lon / 2.0) ** 2
    )
    # Rounding at antipodal points can put h just outside [0, 1].
    h = min(1.0, max(0.0, h))
    return 2.0 * R * math.asin(math.sqrt(h))


def distance_from_path(position, geometry):
    """Return local tangent-plane distance from ``position`` to a polyline.

    The position is the origin for every segment projection.  This is not a
    spherical point-to-line calculation: using the local projection here is an
    explicit part of the navigation contract.
    """

    position = point(position)
    if not isinstance(geometry, (list, tuple)) or len(geometry) < 2:
        raise ValueError("invalid route geometry")
    path = [point(item) for item in geometry]

    cos_latitude = math.cos(math.radians(position["lat"]))

    def xy(item):
        return (
            R
            * cos_latitude
            * math.radians(item["lon"] - position["lon"]),
            R * math.radians(item["lat"] - position["lat"]),
        )

    best = float("inf")
    for a, b in zip(path, path[1:]):
        ax, ay = xy(a)
        bx, by = xy(b)
        dx = bx - ax
        dy = by - ay
        denominator = dx * dx + dy * dy
        if denominator:
            fraction = -(ax * dx + ay * dy) / denominator
            fraction = max(0.0, min(1.0, fraction))
        else:
            # A zero-length segment is a closed segment consisting of one
            # point, so its closest point is that point.
            fraction = 0.0
        closest_x = ax + fraction * dx
        closest_y = ay + fraction * dy
        best = min(best, math.hypot(closest_x, closest_y))
    return best

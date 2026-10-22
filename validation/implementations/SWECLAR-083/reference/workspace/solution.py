"""State transition logic for the local routing component."""

from copy import deepcopy
import math
import os

from geometry import distance_from_path, point
from router import GraphClient, generate_routes


_DEFAULT_THEME = "dark"
_DEFAULT_PROGRESS_THRESHOLD = 30.0


def _fresh_success_state(state):
    """Copy state and remove response-only fields before applying an action."""

    result = deepcopy(state) if isinstance(state, dict) else {}
    result.pop("result", None)
    result.pop("error", None)
    result.setdefault("alternatives", {})
    result.setdefault("points", [])
    result.setdefault("alerts", [])
    result.setdefault("theme", _DEFAULT_THEME)
    return result


def _error_state(state, code):
    """Make an error response without changing the state supplied by a caller."""

    result = deepcopy(state) if isinstance(state, dict) else {}
    # A result is a response detail, not a committed workflow transition.  The
    # server never writes this error response, so the on-disk state is intact.
    result.pop("result", None)
    result["error"] = {"code": code}
    return result


def _finite_nonnegative(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid " + name)
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("invalid " + name)
    if not math.isfinite(value) or value < 0:
        raise ValueError("invalid " + name)
    return value


def _validate_route(route):
    """Validate the route data needed by selection/navigation.

    This validates an already generated route but never constructs geometry
    from an action.  In particular, a caller cannot select an arbitrary route
    ID and cause the component to invent a polyline.
    """

    if not isinstance(route, dict):
        raise ValueError("unknown_route")
    route_id = route.get("route_id")
    geometry = route.get("geometry")
    distance = route.get("distance_miles")
    if not isinstance(route_id, str) or not route_id:
        raise ValueError("unknown_route")
    if not isinstance(geometry, (list, tuple)) or len(geometry) < 2:
        raise ValueError("unknown_route")
    try:
        # Validate every coordinate, while leaving the route itself untouched.
        for item in geometry:
            point(item)
    except ValueError:
        raise ValueError("unknown_route")
    if isinstance(distance, bool) or not isinstance(distance, (int, float)):
        raise ValueError("unknown_route")
    try:
        distance = float(distance)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("unknown_route")
    if not math.isfinite(distance) or distance < 0:
        raise ValueError("unknown_route")
    return route


def _selected_route(state):
    route = state.get("selected_route")
    if route is None:
        raise ValueError("route_not_selected")
    try:
        return _validate_route(route)
    except ValueError:
        raise ValueError("route_not_selected")


def _configured_client(client):
    if client is not None:
        if not callable(getattr(client, "fetch", None)):
            raise ValueError("provider_failed")
        return client
    # The optional argument is useful to callers with a fixture client.  The
    # web service supplies its configured GraphClient; when called directly we
    # use the same GRAPH_URL convention rather than accepting graph data from
    # an action.
    url = os.environ.get("GRAPH_URL")
    if not url:
        raise ValueError("provider_failed")
    try:
        return GraphClient(url)
    except Exception:
        raise ValueError("provider_failed")


def process_navigation_action(state, action, client=None):
    """Apply one navigation action and return a new local workflow state.

    All work happens on a deep copy.  If anything is rejected, the returned
    object is an error view of the prior state and the caller (the HTTP server)
    does not persist it.
    """

    try:
        if not isinstance(action, dict):
            raise ValueError("unknown_action")
        # Copy actions too: this keeps the transition independent of mutable
        # objects supplied by a caller/fake client, even though we only read
        # the action below.
        action = deepcopy(action)
        kind = action.get("type")
        if not isinstance(kind, str):
            raise ValueError("unknown_action")

        out = _fresh_success_state(state)

        if kind == "generate_alternatives":
            start = action.get("start_node")
            if not isinstance(start, str) or not start:
                raise ValueError("invalid start")
            requested = _finite_nonnegative(
                action.get("requested_miles"), "requested_miles"
            )
            tolerance = _finite_nonnegative(
                action.get("tolerance", 0), "tolerance"
            )

            graph_client = _configured_client(client)
            try:
                network = graph_client.fetch(start)
            except Exception:
                # Transport/provider failures are not input-validation errors
                # and must not expose arbitrary exception text as state.
                raise ValueError("provider_failed")
            routes = generate_routes(network, start, requested, tolerance)
            if not routes:
                raise ValueError("no_route_within_tolerance")

            out["alternatives"] = {
                route["route_id"]: deepcopy(route) for route in routes
            }
            # Regeneration is the one operation that intentionally invalidates
            # selection and navigation.  Other persistent workflow fields are
            # retained.
            out.pop("selected_route", None)
            out.pop("navigation", None)
            out["result"] = {"routes": deepcopy(routes)}

        elif kind == "place_point":
            placed = point(action)
            if not isinstance(out.get("points"), list):
                raise ValueError("invalid state")
            out["points"].append(placed)
            out["result"] = deepcopy(placed)

        elif kind == "select_route":
            route_id = action.get("route_id")
            alternatives = out.get("alternatives")
            if (
                not isinstance(route_id, str)
                or not route_id
                or not isinstance(alternatives, dict)
                or route_id not in alternatives
            ):
                raise ValueError("unknown_route")
            route = alternatives[route_id]
            _validate_route(route)
            if route.get("route_id") != route_id:
                raise ValueError("unknown_route")
            out["selected_route"] = deepcopy(route)
            # Selecting a different route makes any previous navigation
            # session inapplicable.
            out.pop("navigation", None)
            out["result"] = deepcopy(route)

        elif kind == "start_navigation":
            route = _selected_route(out)
            # Referencing the route above is intentional: a hand-edited or
            # otherwise stale selected_route is not allowed to start a session
            # with unusable geometry.
            del route
            out["navigation"] = {"active": True, "last_position": None}
            out["result"] = {"active": True}

        elif kind == "progress":
            navigation = out.get("navigation")
            event_id = action.get("event_id")
            if (
                not isinstance(navigation, dict)
                or not navigation.get("active")
                or not isinstance(event_id, str)
                or not event_id
            ):
                raise ValueError("progress_denied")

            threshold = action.get(
                "threshold_meters", _DEFAULT_PROGRESS_THRESHOLD
            )
            threshold = _finite_nonnegative(threshold, "threshold")
            position = point(action.get("position"))
            route = _selected_route(out)
            geometry = route["geometry"]
            distance = distance_from_path(position, geometry)

            alerts = out.get("alerts")
            if not isinstance(alerts, list):
                raise ValueError("invalid state")

            # The valid position is recorded even when it produces an alert.
            # It is assigned only after all validation/calculation succeeds,
            # preserving atomicity on malformed coordinates.
            navigation["last_position"] = deepcopy(position)
            off_route = distance > threshold  # equality is deliberately safe
            if off_route:
                already_alerted = any(
                    isinstance(alert, dict)
                    and alert.get("event_id") == event_id
                    for alert in alerts
                )
                if not already_alerted:
                    alerts.append(
                        {
                            "event_id": event_id,
                            "kind": "off_route",
                            "vibrate": True,
                        }
                    )
            out["result"] = {
                "off_route": off_route,
                "distance_meters": distance,
            }

        elif kind == "set_theme":
            theme = action.get("theme")
            if theme not in ("light", "dark"):
                raise ValueError("invalid_theme")
            out["theme"] = theme
            out["result"] = {"theme": theme}

        else:
            raise ValueError("unknown_action")

        return out

    except ValueError as exc:
        code = str(exc) or "invalid_action"
        return _error_state(state, code)
    except Exception:
        # A malformed provider response, unexpected fake client failure, or
        # malformed pre-existing state is rejected without a partial commit.
        return _error_state(state, "provider_failed")

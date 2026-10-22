"""Graph HTTP adapter and deterministic loop enumeration."""

import hashlib
import json
import math
from urllib.request import Request, urlopen

from geometry import METRES_PER_MILE, meters, point


MAX_SEARCH_STATES = 100000
MIN_DISTINCT_NODES = 3
MAX_DISTINCT_NODES = 10


class GraphClient:
    """Small HTTP client for the configured graph provider.

    The provider is deliberately contacted with a POST for every generation
    request.  No graph data is cached here: a new generation action always
    reads the currently configured graph.
    """

    def __init__(self, url):
        if not isinstance(url, str) or not url:
            raise ValueError("provider_failed")
        self.url = url

    def fetch(self, start_node):
        body = json.dumps({"start_node": start_node}, separators=(",", ":")).encode(
            "utf-8"
        )
        request = Request(
            self.url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            raw = response.read()
        return json.loads(raw)


def _finite_number(value, name, *, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid " + name)
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("invalid " + name)
    if not math.isfinite(value):
        raise ValueError("invalid " + name)
    if nonnegative and value < 0:
        raise ValueError("invalid " + name)
    return value


def _normalise_network(network, start):
    """Validate the provider response and make deterministic adjacency lists."""

    if not isinstance(network, dict):
        raise ValueError("invalid network")
    nodes = network.get("nodes")
    edges = network.get("edges")
    if not isinstance(nodes, dict) or not isinstance(edges, (list, tuple)):
        raise ValueError("invalid network")

    # The README's 3--24 node/60-edge figures describe the provider's
    # benchmark boundary.  The traversal cap below remains the hard safety
    # limit, while allowing a structurally valid small graph to simply produce
    # no qualifying loop when it has too few nodes.
    if not isinstance(start, str) or not start or start not in nodes:
        raise ValueError("invalid start")

    coordinates = {}
    for node_id, value in nodes.items():
        if not isinstance(node_id, str):
            raise ValueError("invalid network")
        coordinates[node_id] = point(value)

    adjacency_sets = {node_id: set() for node_id in coordinates}
    for edge in edges:
        # The documented shape is [from, to].  Accepting trailing values is
        # intentional: providers sometimes attach a distance label, which is
        # untrusted and must not affect route geometry or filtering.
        if not isinstance(edge, (list, tuple)) or len(edge) < 2:
            raise ValueError("invalid network")
        source, destination = edge[0], edge[1]
        if (
            not isinstance(source, str)
            or not isinstance(destination, str)
            or source not in coordinates
            or destination not in coordinates
        ):
            raise ValueError("invalid network")
        adjacency_sets[source].add(destination)

    # Node identifiers in the JSON graph are strings.  Sorting them makes both
    # traversal and the eventual result independent of provider edge order.
    adjacency = {
        node_id: sorted(neighbours) for node_id, neighbours in adjacency_sets.items()
    }
    return coordinates, adjacency


def _route_id(sequence):
    # JSON encoding avoids delimiter ambiguities (for example, node IDs that
    # themselves contain a separator).  Including the closed sequence makes
    # the identity explicit and is stable across edge ordering.
    encoded = json.dumps(
        list(sequence), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return "route-" + hashlib.sha256(encoded).hexdigest()


def _make_route(sequence, coordinates):
    geometry = [dict(coordinates[node_id]) for node_id in sequence]
    distance_metres = sum(
        meters(left, right) for left, right in zip(geometry, geometry[1:])
    )
    return {
        "route_id": _route_id(sequence),
        "geometry": geometry,
        "distance_miles": distance_metres / METRES_PER_MILE,
    }


def generate_routes(network, start, requested, tolerance):
    """Enumerate and distance-filter simple directed loops.

    A search state is a simple path without its closing copy of ``start``.
    The initial ``[start]`` path counts as state one.  Closing an eligible
    path is an edge examination rather than a new simple-path state.  If a new
    path would be state 100001, the whole generation raises before returning
    partial alternatives.
    """

    requested = _finite_number(requested, "requested_miles", nonnegative=True)
    tolerance = _finite_number(tolerance, "tolerance", nonnegative=True)
    coordinates, adjacency = _normalise_network(network, start)

    routes = []
    search_states = 1  # The initial path is a traversal state.

    def walk(path):
        nonlocal search_states
        current = path[-1]
        for neighbour in adjacency[current]:
            if neighbour == start:
                if MIN_DISTINCT_NODES <= len(path) <= MAX_DISTINCT_NODES:
                    closed = path + [start]
                    route = _make_route(closed, coordinates)
                    if abs(route["distance_miles"] - requested) <= tolerance:
                        routes.append(route)
                continue

            if neighbour in path or len(path) >= MAX_DISTINCT_NODES:
                continue

            # Do not visit state 100001.  Raising here causes the caller to
            # retain the old state rather than saving a partial search result.
            if search_states >= MAX_SEARCH_STATES:
                raise ValueError("search_limit")
            search_states += 1
            walk(path + [neighbour])

    walk([start])
    routes.sort(
        key=lambda route: (
            abs(route["distance_miles"] - requested),
            route["route_id"],
        )
    )
    return routes

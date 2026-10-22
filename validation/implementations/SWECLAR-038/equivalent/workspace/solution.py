"""Exact top-k optimizer for the five-slot lineup problem.

The public entry point deliberately keeps only the information needed by the
optimizer from each player record.  The implementation splits the possible
position patterns into six disjoint cases and uses best-first enumeration for
both the small per-position permutation lists and their Cartesian products.
That avoids materialising the (potentially very large) set of all lineups.
"""

import heapq
import itertools
import math
from collections import namedtuple
from decimal import Decimal
from fractions import Fraction
from numbers import Integral, Rational, Real
from typing import Any


# A private immutable representation means that sorting the working data can
# never change a caller-owned record or list.
_Player = namedtuple("_Player", ("id", "position", "points", "exact_points"))

# A choice is (score, player_ids), where player_ids are in the ordered slots
# occupied by that choice.  Lists of choices are always in descending score,
# then ascending player-id tuple order.

_VALID_POSITIONS = frozenset(("QB", "RB", "WR", "TE"))


# ---------------------------------------------------------------------------
# Validation


def _valid_projection(value: Any) -> bool:
    """Return whether *value* is a finite, non-Boolean real number.

    JSON supplies ints and floats, but accepting other standard real numeric
    types is harmless for direct Python callers.  An integer is finite even
    when converting it to a float would overflow.
    """

    if isinstance(value, bool):
        return False
    if isinstance(value, Decimal):
        return value.is_finite()
    if not isinstance(value, Real):
        return False
    if isinstance(value, Rational):
        return True
    try:
        return math.isfinite(value)
    except (TypeError, OverflowError, ValueError):
        return False


def _invalid_request() -> dict:
    return {"error": {"code": "invalid_request"}}


def _invalid_player() -> dict:
    return {"error": {"code": "invalid_player"}}


def _validate_players(players: Any):
    """Validate all records, then check IDs for duplication.

    The second pass is intentional: a malformed record takes precedence over a
    duplicate ID, as required by the public contract.
    """

    if not isinstance(players, list):
        return None, {"error": {"code": "invalid_players"}}

    parsed = []
    for record in players:
        if not isinstance(record, dict):
            return None, _invalid_player()

        # Use membership first so records with unusual mapping subclasses do
        # not accidentally turn a missing field into an arbitrary exception.
        if "id" not in record or "position" not in record or "projected_points" not in record:
            return None, _invalid_player()

        player_id = record["id"]
        position = record["position"]
        points = record["projected_points"]

        if not isinstance(player_id, str) or not player_id:
            return None, _invalid_player()
        if not isinstance(position, str) or position not in _VALID_POSITIONS:
            return None, _invalid_player()
        if not _valid_projection(points):
            return None, _invalid_player()

        parsed.append(_Player(player_id, position, points, _as_exact_points(points)))

    seen = set()
    for player in parsed:
        if player.id in seen:
            return None, {"error": {"code": "duplicate_player_id"}}
        seen.add(player.id)

    return parsed, None


# ---------------------------------------------------------------------------
# Small numeric and combinatorial helpers


def _as_exact_points(value):
    """Make a comparable, associative representation of a real projection.

    ``Fraction`` gives every JSON integer/float an exact value for ranking.
    In particular, all permutations of the same five players receive the
    same score even when ordinary binary floating-point addition would round
    intermediate results in different ways.  The public score is converted
    back to an ordinary JSON number at the boundary.
    """

    if isinstance(value, Integral):
        return Fraction(int(value), 1)
    if isinstance(value, float):
        return Fraction.from_float(value)
    if isinstance(value, Decimal):
        return Fraction(value)
    try:
        return Fraction(value)
    except (TypeError, ValueError, ZeroDivisionError):
        # The validator admits Real subclasses.  Their float conversion is a
        # reasonable fallback for a non-standard subclass while normal JSON
        # inputs take one of the exact branches above.
        return Fraction.from_float(float(value))


def _add_values(values):
    """Add internal exact projection values."""

    result = Fraction(0, 1)
    for value in values:
        result += value
    return result


def _public_score(exact_score, values):
    """Convert an exact score to a JSON-compatible numeric value."""

    if all(isinstance(value, Integral) and not isinstance(value, bool) for value in values):
        return int(exact_score)
    # For the JSON-facing use case projections are ints/floats.  A float is a
    # stable, serialisable approximation for other accepted real subclasses.
    try:
        converted = float(exact_score)
    except OverflowError:
        converted = None
    if converted is not None and math.isfinite(converted):
        return converted
    # A sum of finite, very large projections can exceed the float range.
    # Keep the wire result numeric and finite rather than returning infinity
    # (the console encoder quite correctly rejects non-finite JSON values).
    return int(exact_score)


def _falling_count(n: int, slots: int) -> int:
    result = 1
    for offset in range(slots):
        result *= n - offset
    return result


def _combination_count(n: int, slots: int) -> int:
    if slots < 0 or slots > n:
        return 0
    # slots is at most three in this problem, so this avoids depending on a
    # particular Python version's math.comb implementation and is cheap.
    result = 1
    for i in range(1, slots + 1):
        result = result * (n - slots + i) // i
    return result


# ---------------------------------------------------------------------------
# Top choices for one repeated position category


def _top_unordered_combinations(players, slots: int, amount: int):
    """Return the best ``amount`` index combinations of ``slots`` players.

    ``players`` must be sorted by descending projection and then ID.  The
    index lattice has monotone scores, so a heap visits combinations in exact
    score/ID order without walking the full n-choose-slots space.
    """

    n = len(players)
    total = _combination_count(n, slots)
    wanted = min(amount, total)
    if wanted <= 0:
        return []

    initial = tuple(range(slots))

    def make_entry(indices):
        chosen = tuple(players[index] for index in indices)
        score = _add_values(player.exact_points for player in chosen)
        # The set's sorted ID tuple is the lexicographically smallest ordered
        # assignment made from this set and is the right tie key for the
        # combination lattice.
        id_key = tuple(sorted(player.id for player in chosen))
        return (-score, id_key, indices, score, chosen)

    heap = [make_entry(initial)]
    visited = {initial}
    answer = []

    while heap and len(answer) < wanted:
        _negative_score, _id_key, indices, score, chosen = heapq.heappop(heap)
        answer.append((score, chosen))

        for position in range(slots):
            successor = list(indices)
            successor[position] += 1
            if successor[position] >= n:
                continue
            if position and successor[position] <= successor[position - 1]:
                continue
            if position + 1 < slots and successor[position] >= successor[position + 1]:
                continue
            successor = tuple(successor)
            if successor in visited:
                continue
            visited.add(successor)
            heapq.heappush(heap, make_entry(successor))

    return answer


def _make_group_choices(players, slots: int, amount: int):
    """Return top ordered, distinct-player choices for one position group."""

    if slots == 0:
        return [(0, ())]

    # Sorting by this key makes the one-slot case and the index lattice
    # monotone.  IDs are unique by the time this helper is called.
    ordered = sorted(players, key=lambda player: (-player.exact_points, player.id))

    if slots == 1:
        return [(player.exact_points, (player.id,)) for player in ordered[:amount]]

    # There are slots! assignments for every unordered set.  The first
    # ``amount`` sets are enough to contain the first ``amount`` ordered
    # assignments: any set after that has at least ``amount`` earlier sets,
    # and each earlier set contributes an assignment no later than it on a
    # score/lexicographic ordering.  We then sort all permutations so ties
    # between different sets receive their exact ordered-ID ranking.
    set_choices = _top_unordered_combinations(ordered, slots, amount)
    candidates = []
    for score, chosen in set_choices:
        for permutation in itertools.permutations(chosen):
            candidates.append((score, tuple(player.id for player in permutation)))

    candidates.sort(key=lambda choice: (-choice[0], choice[1]))
    return candidates[:amount]


# ---------------------------------------------------------------------------
# Product enumeration for one position pattern


def _pattern_stream(pattern, by_position, amount, group_cache):
    """Yield a pattern's prefix in ranking order.

    Each concrete position pattern is a Cartesian product of already-ranked
    per-position choices.  The product frontier is itself monotone, so a
    heap can expose its next member without constructing the complete product.
    Keeping this as a stream is useful when several patterns are combined: a
    pattern that contributes no global top-k result is never expanded further.
    """

    # Group slots by category.  Every category's slots are kept in their
    # global slot order, which is important for the lexicographic tie proof.
    slots_by_position = {position: [] for position in _VALID_POSITIONS}
    for slot, position in enumerate(pattern):
        slots_by_position[position].append(slot)

    dimensions = []
    for position, slots in slots_by_position.items():
        if not slots:
            continue
        slot_count = len(slots)
        cache_key = (position, slot_count)
        if cache_key not in group_cache:
            group_cache[cache_key] = _make_group_choices(
                by_position[position], slot_count, amount
            )
        choices = group_cache[cache_key]
        if not choices:
            return
        dimensions.append((tuple(slots), choices))

    # Put dimensions in global first-slot order.  The exact order does not
    # affect additive scores, but it keeps construction and numeric addition
    # intuitive and deterministic.
    dimensions.sort(key=lambda dimension: dimension[0][0])

    product_size = 1
    for _slots, choices in dimensions:
        product_size *= len(choices)
    # If a category has fewer than the requested choices, its list is already
    # exhaustive.  Otherwise no top-amount product can need an index beyond
    # amount in any dimension.
    wanted = min(amount, product_size)
    if wanted <= 0:
        return

    def make_entry(state):
        selected = [
            choices[state[index]]
            for index, (_slots, choices) in enumerate(dimensions)
        ]
        score = _add_values(choice[0] for choice in selected)
        ids = [None] * len(pattern)
        for (slots, _choices), choice in zip(dimensions, selected):
            for slot, player_id in zip(slots, choice[1]):
                ids[slot] = player_id
        id_tuple = tuple(ids)
        return (-score, id_tuple, state, score, id_tuple)

    frontier = [make_entry(tuple(0 for _ in dimensions))]
    visited = {tuple(0 for _ in dimensions)}
    produced = 0

    while frontier and produced < wanted:
        _negative_score, _id_key, state, score, ids = heapq.heappop(frontier)
        produced += 1
        yield score, ids

        for dimension in range(len(dimensions)):
            successor = list(state)
            successor[dimension] += 1
            if successor[dimension] >= len(dimensions[dimension][1]):
                continue
            successor = tuple(successor)
            if successor in visited:
                continue
            visited.add(successor)
            heapq.heappush(frontier, make_entry(successor))


def _merge_pattern_streams(patterns, pattern_counts, by_position, amount, group_cache):
    """Return the first ``amount`` choices from all ranked pattern streams.

    The six concrete patterns are disjoint and each stream is sorted using the
    same score/ID key.  A k-way heap merge therefore has the same result as
    sorting their concatenation, while retaining only one pending choice per
    pattern and the requested output prefix.
    """

    streams = []
    frontier = []
    for pattern_index, (pattern, pattern_count) in enumerate(
        zip(patterns, pattern_counts)
    ):
        if not pattern_count:
            continue
        stream = _pattern_stream(pattern, by_position, amount, group_cache)
        try:
            score, ids = next(stream)
        except StopIteration:
            continue
        streams.append(stream)
        stream_number = len(streams) - 1
        # The stream number makes heap entries totally ordered even for an
        # unusual direct caller whose data produces equal IDs in two patterns.
        heapq.heappush(
            frontier,
            (-score, ids, pattern_index, stream_number, score, ids),
        )

    selected = []
    while frontier and len(selected) < amount:
        _negative_score, _id_key, pattern_index, stream_number, score, ids = (
            heapq.heappop(frontier)
        )
        selected.append((score, ids))
        stream = streams[stream_number]
        try:
            next_score, next_ids = next(stream)
        except StopIteration:
            continue
        heapq.heappush(
            frontier,
            (
                -next_score,
                next_ids,
                pattern_index,
                stream_number,
                next_score,
                next_ids,
            ),
        )

    return selected


# The six cases are disjoint because they specify the concrete position of
# each flexible slot.  The tuple order is exactly QB, RB, WR, WR-or-TE, FLEX.
_PATTERNS = (
    ("QB", "RB", "WR", "WR", "RB"),
    ("QB", "RB", "WR", "WR", "WR"),
    ("QB", "RB", "WR", "WR", "TE"),
    ("QB", "RB", "WR", "TE", "RB"),
    ("QB", "RB", "WR", "TE", "WR"),
    ("QB", "RB", "WR", "TE", "TE"),
)


def optimize_lineups(players: list[dict], limit: int, mode: str) -> dict:
    """Return the exact highest-scoring ordered lineups.

    ``deep`` and ``realtime`` intentionally share this implementation: both
    modes have exact-result semantics in the public contract.
    """

    # Request parameters are checked before looking at player data.
    if (
        isinstance(limit, bool)
        or not isinstance(limit, Integral)
        or limit <= 0
        or not isinstance(mode, str)
        or mode not in ("deep", "realtime")
    ):
        return _invalid_request()

    # Convert an Integral subclass to a plain int so later range/min
    # operations cannot invoke user-defined arithmetic unexpectedly.
    requested = int(limit)
    parsed, error = _validate_players(players)
    if error is not None:
        return error

    by_position = {position: [] for position in _VALID_POSITIONS}
    for player in parsed:
        by_position[player.position].append(player)

    # Count all valid ordered assignments independently of the requested
    # output prefix.  Falling factorials account for distinct IDs in each
    # repeated concrete position category.
    considered = 0
    pattern_counts = []
    for pattern in _PATTERNS:
        counts = {position: pattern.count(position) for position in _VALID_POSITIONS}
        pattern_count = 1
        for position, slots in counts.items():
            if slots:
                pattern_count *= _falling_count(len(by_position[position]), slots)
        pattern_counts.append(pattern_count)
        considered += pattern_count

    if considered == 0:
        unused = sorted(player.id for player in parsed)
        return {"lineups": [], "considered": 0, "unused_player_ids": unused}

    amount = min(requested, considered)
    group_cache = {}
    # Every pattern stream is individually ranked.  Merging the streams avoids
    # materialising six separate candidate prefixes before selecting the global
    # prefix, without changing the score/ID ordering.
    selected = _merge_pattern_streams(
        _PATTERNS, pattern_counts, by_position, amount, group_cache
    )

    used = {player_id for _score, ids in selected for player_id in ids}
    unused = sorted(player.id for player in parsed if player.id not in used)

    points_by_id = {player.id: player.points for player in parsed}
    lineups = []
    for exact_score, ids in selected:
        values = [points_by_id[player_id] for player_id in ids]
        lineups.append({
            "player_ids": list(ids),
            "score": _public_score(exact_score, values),
        })
    return {
        "lineups": lineups,
        "considered": considered,
        "unused_player_ids": unused,
    }

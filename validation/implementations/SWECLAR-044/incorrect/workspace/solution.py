"""Reference workflow for raw-measurement trend state."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
import math
import re
from typing import Any

from fetcher import fetch_text as default_fetch_text
from measurements import parse_measurements


_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def _error(state: dict[str, Any], code: str) -> dict[str, Any]:
    """Return an untouched state copy with the contract's error shape."""

    result = deepcopy(state)
    result["error"] = {"code": code}
    return result


def _successful_copy(state: dict[str, Any]) -> dict[str, Any]:
    """Copy state and remove transient output from a prior action."""

    result = deepcopy(state)
    result.pop("result", None)
    result.pop("error", None)
    return result


def _collection(state: dict[str, Any], name: str) -> dict[Any, Any]:
    value = state.get(name)
    return value if isinstance(value, dict) else {}


def _has_key(mapping: Any, key: Any) -> bool:
    if not isinstance(mapping, dict):
        return False
    try:
        return key in mapping
    except TypeError:
        return False


def _known_category(state: dict[str, Any], category_id: Any) -> bool:
    return _has_key(_collection(state, "categories"), category_id)


def _valid_month(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    match = _MONTH_RE.fullmatch(value)
    if match is None:
        return False
    year = int(match.group(1))
    month = int(match.group(2))
    return 1 <= year <= 9999 and 1 <= month <= 12


def _canonical_month(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if _valid_month(value) else None


def _numeric_growth(value: Any) -> float | None:
    """Return a finite numeric growth value, or ``None`` for unknown data."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _growth_and_classification(history: list[dict[str, Any]]) -> tuple[Any, str]:
    """Compute the public two-latest-month growth convention."""

    if len(history) < 2:
        return None, "insufficient_baseline"

    previous = history[-2].get("count")
    latest = history[-1].get("count")
    if isinstance(previous, bool) or isinstance(latest, bool):
        return None, "insufficient_baseline"
    if not isinstance(previous, (int, float)) or not isinstance(latest, (int, float)):
        return None, "insufficient_baseline"
    try:
        previous_number = Decimal(str(previous))
        latest_number = Decimal(str(latest))
    except (InvalidOperation, ValueError, TypeError):
        return None, "insufficient_baseline"
    if not previous_number.is_finite() or not latest_number.is_finite():
        return None, "insufficient_baseline"

    if previous_number == 0:
        if latest_number == 0:
            return 0, "regular"
        return None, "insufficient_baseline"

    # Counts are validated as non-negative by the CSV parser.  Keep the
    # defensive branch for state supplied by a caller outside that parser.
    if previous_number < 0 or latest_number < 0:
        return None, "insufficient_baseline"

    # Use Decimal for the calculation and threshold decisions so a decimal
    # source value exactly on 15% or 30% is not moved across a boundary by a
    # binary floating-point rounding artefact.
    with localcontext() as context:
        context.prec = max(
            60,
            len(previous_number.as_tuple().digits),
            len(latest_number.as_tuple().digits),
        )
        delta = latest_number - previous_number
        growth_decimal = delta / previous_number * Decimal(100)
        try:
            growth = float(growth_decimal)
        except (OverflowError, ValueError):
            growth = math.inf if delta > 0 else -math.inf

        if delta * Decimal(100) > previous_number * Decimal(90):
            classification = "hot"
        elif delta * Decimal(100) >= previous_number * Decimal(15):
            classification = "rising"
        elif delta >= 0:
            classification = "regular"
        else:
            classification = "declining"

    # A valid finite count pair can theoretically have a relative change too
    # large for a Python float.  Keep the JSON result finite while preserving
    # its ordering/classification direction.
    if not math.isfinite(growth):
        growth = float.fromhex("0x1.fffffffffffffp+1023")
        if latest_number < previous_number:
            growth = -growth
    return growth, classification


def _merge_history(
    existing_history: Any, incoming_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Upsert source rows into history, sort, and retain the latest twelve."""

    by_month: dict[str, dict[str, Any]] = {}
    if isinstance(existing_history, list):
        for item in existing_history:
            if not isinstance(item, dict):
                continue
            month = item.get("month")
            if not isinstance(month, str):
                continue
            # Existing state is promised valid.  Copying the item rather than
            # rebuilding it also preserves any non-conflicting history
            # metadata supplied by a client.
            by_month[month] = deepcopy(item)

    for row in incoming_rows:
        month = row["month"]
        if month in by_month:
            record = by_month[month]
            record["month"] = month
            record["count"] = row["count"]
        else:
            by_month[month] = {"month": month, "count": row["count"]}

    history = list(by_month.values())
    history.sort(key=lambda item: item.get("month", ""))
    return history[-12:]


def _rows_by_trend(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record["trend_id"], []).append(record)
    return grouped


def _sync_source(state: dict[str, Any], action: dict[str, Any], fetch_text: Any) -> dict[str, Any]:
    category_id = action.get("category_id")
    if not _known_category(state, category_id):
        return _error(state, "invalid_category")

    url = action.get("url")
    if not isinstance(url, str) or not url.strip():
        return _error(state, "invalid_action")

    reader = fetch_text if fetch_text is not None else default_fetch_text
    try:
        raw_csv = reader(url)
    except Exception:
        # Retrieval and transport errors are intentionally distinct from an
        # invalid body returned by a successful retrieval.
        return _error(state, "fetch_failed")

    try:
        records = parse_measurements(raw_csv)
    except Exception:
        # The parser's validation error, and any unexpected parser/type
        # failure, become the required all-or-nothing source error rather than
        # a partial update or an uncaught exception.
        return _error(state, "invalid_source")

    original_trends = _collection(state, "trends")

    # Validate every row against the pre-update state before constructing the
    # output.  In particular, a later bad row cannot leave an earlier row
    # applied.
    for record in records:
        trend_id = record["trend_id"]
        if not _has_key(original_trends, trend_id):
            continue
        existing = original_trends[trend_id]
        if not isinstance(existing, dict):
            return _error(state, "invalid_source")
        if existing.get("category_id") != category_id:
            return _error(state, "invalid_source")
        existing_keyword = existing.get("keyword")
        if not isinstance(existing_keyword, str):
            return _error(state, "invalid_source")
        if existing_keyword.strip() != record["keyword"]:
            return _error(state, "invalid_source")

    if not records:
        result = _successful_copy(state)
        if not isinstance(result.get("trends"), dict):
            result["trends"] = {}
        return result

    result = _successful_copy(state)
    trends = result.get("trends")
    if not isinstance(trends, dict):
        trends = {}
        result["trends"] = trends

    grouped = _rows_by_trend(records)
    for trend_id, rows in grouped.items():
        if _has_key(original_trends, trend_id):
            trend = trends[trend_id]
            history = _merge_history(trend.get("history"), rows)
            trend["history"] = history
            trend["growth"], trend["classification"] = _growth_and_classification(history)
        else:
            keyword = rows[0]["keyword"]
            history = _merge_history([], rows)
            growth, classification = _growth_and_classification(history)
            trends[trend_id] = {
                "trend_id": trend_id,
                "category_id": category_id,
                "keyword": keyword,
                "history": history,
                "growth": growth,
                "classification": classification,
            }

    return result


def _category_view(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    category_ids = action.get("category_ids")
    if not isinstance(category_ids, list) or len(category_ids) != 1:
        return _error(state, "invalid_category_selection")
    category_id = category_ids[0]
    if not _known_category(state, category_id):
        return _error(state, "invalid_category")

    result = _successful_copy(state)
    records: list[tuple[Any, dict[str, Any]]] = []
    for mapping_id, trend in _collection(state, "trends").items():
        if not isinstance(trend, dict) or trend.get("category_id") != category_id:
            continue
        records.append((mapping_id, deepcopy(trend)))

    def sort_key(item: tuple[Any, dict[str, Any]]) -> tuple[Any, ...]:
        mapping_id, trend = item
        growth = _numeric_growth(trend.get("growth"))
        unknown = growth is None
        keyword = trend.get("keyword")
        keyword_key = keyword.casefold() if isinstance(keyword, str) else str(keyword).casefold()
        trend_id = trend.get("trend_id", mapping_id)
        trend_id_key = trend_id if isinstance(trend_id, str) else str(trend_id)
        if unknown:
            return (1, 0, keyword_key, trend_id_key)
        return (0, -growth, keyword_key, trend_id_key)

    records.sort(key=sort_key)
    result["result"] = {"trends": [trend for _, trend in records]}
    return result


def _watch_action(state: dict[str, Any], action: dict[str, Any], operation: str) -> dict[str, Any]:
    user_id = action.get("user_id")
    if not isinstance(user_id, str) or not user_id.strip():
        return _error(state, "invalid_user")

    trend_id = action.get("trend_id")
    trends = _collection(state, "trends")
    if not _has_key(trends, trend_id):
        return _error(state, "unknown_trend")

    result = _successful_copy(state)
    watchlists = result.get("watchlists")
    if not isinstance(watchlists, dict):
        watchlists = {}
        result["watchlists"] = watchlists

    existing = watchlists.get(user_id)
    current = list(existing) if isinstance(existing, list) else []
    if operation == "watch":
        if trend_id not in current:
            current.append(trend_id)
        # A watch operation creates the user's list, including when it was
        # previously absent.  List order is therefore insertion order.
        watchlists[user_id] = current
    else:
        if user_id in watchlists:
            current = [item for item in current if item != trend_id]
            watchlists[user_id] = current
        # Removing from a user who has no list is an idempotent no-op; do not
        # manufacture a state entry just for that no-op.

    result["result"] = {"trend_ids": deepcopy(current)}
    return result


def _normalised_suggestions(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        trimmed = value.strip()
        if not trimmed:
            continue
        key = trimmed.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(trimmed)
    return output


def _discover(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    seed = action.get("seed")
    if not isinstance(seed, str):
        return _error(state, "invalid_seed")
    seed_key = seed.strip().casefold()

    suggestions = _collection(state, "suggestions")
    values: Any = []
    if seed_key in suggestions:
        values = suggestions[seed_key]
    else:
        # The documented state uses normalised keys.  This fallback keeps the
        # operation tolerant of a legacy state without changing that state.
        for key, candidate_values in suggestions.items():
            if isinstance(key, str) and key.strip().casefold() == seed_key:
                values = candidate_values
                break

    result = _successful_copy(state)
    result["result"] = {"suggestions": _normalised_suggestions(values)}
    return result


def _new_trend_id(trends: dict[Any, Any]) -> str:
    used: set[Any] = set()
    for mapping_id, trend in trends.items():
        try:
            used.add(mapping_id)
        except TypeError:
            pass
        if isinstance(trend, dict):
            trend_id = trend.get("trend_id")
            if isinstance(trend_id, str):
                used.add(trend_id)

    number = 1
    while True:
        candidate = f"generated-{number}"
        if candidate not in used:
            return candidate
        number += 1


def _generate_keywords(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    category_id = action.get("category_id")
    if not _known_category(state, category_id):
        return _error(state, "invalid_category")

    month = _canonical_month(action.get("month"))
    if month is None:
        return _error(state, "invalid_month")

    generation_log = _collection(state, "generation_log")
    previous_months = generation_log.get(category_id, [])
    if isinstance(previous_months, list) and month in previous_months:
        return _error(state, "generation_already_done")

    candidates = action.get("candidates", [])
    if not isinstance(candidates, list):
        return _error(state, "invalid_candidates")

    result = _successful_copy(state)
    trends = result.get("trends")
    if not isinstance(trends, dict):
        trends = {}
        result["trends"] = trends

    existing_keywords: set[str] = set()
    for trend in trends.values():
        if not isinstance(trend, dict) or trend.get("category_id") != category_id:
            continue
        keyword = trend.get("keyword")
        if isinstance(keyword, str):
            existing_keywords.add(keyword.strip().casefold())

    added_ids: list[str] = []
    # The quota applies to the supplied candidate batch.  Invalid and blank
    # entries are still skipped, while valid candidates retain their order and
    # first spelling.
    for candidate in candidates[:25]:
        if not isinstance(candidate, str):
            continue
        keyword = candidate.strip()
        if not keyword:
            continue
        key = keyword.casefold()
        if key in existing_keywords:
            continue
        existing_keywords.add(key)

        trend_id = _new_trend_id(trends)
        trends[trend_id] = {
            "trend_id": trend_id,
            "category_id": category_id,
            "keyword": keyword,
            "history": [],
            "growth": None,
            "classification": "insufficient_baseline",
        }
        added_ids.append(trend_id)

    output_log = result.get("generation_log")
    if not isinstance(output_log, dict):
        output_log = {}
        result["generation_log"] = output_log
    logged = output_log.get(category_id)
    if not isinstance(logged, list):
        logged = []
    else:
        logged = list(logged)
    logged.append(month)
    output_log[category_id] = logged

    result["result"] = {"added_ids": added_ids}
    return result


def process_trend_action(state: dict, action: dict, fetch_text=None) -> dict:
    """Apply one trend workflow action without mutating either input object."""

    if not isinstance(state, dict):
        return {"error": {"code": "invalid_state"}}
    if not isinstance(action, dict):
        return _error(state, "invalid_action")

    action_type = action.get("type")
    if action_type == "sync_source":
        return _sync_source(state, action, fetch_text)
    if action_type == "category_view":
        return _category_view(state, action)
    if action_type == "watch":
        return _watch_action(state, action, "watch")
    if action_type == "unwatch":
        return _watch_action(state, action, "unwatch")
    if action_type == "discover":
        return _discover(state, action)
    if action_type == "generate_keywords":
        return _generate_keywords(state, action)
    return _error(state, "unknown_action")


__all__ = ["process_trend_action"]

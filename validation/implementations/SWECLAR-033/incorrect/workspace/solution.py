"""State transition entry point for the exhibition ingestion component."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import hashlib
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fetcher import fetch_text as default_fetch_text
from feed_parser import (
    InvalidExhibitionError,
    InvalidFeedError,
    UnsupportedFeedError,
    is_supported_feed_type,
    parse_feed,
)


def _copy_state(state: Any) -> Dict[str, Any]:
    """Make the state transition independent of every input object."""

    copied = deepcopy(state)
    if not isinstance(copied, dict):
        # The documented input is a dictionary.  Returning a useful state for
        # an invalid caller is preferable to mutating or raising half-way
        # through a transition.
        copied = {}
    if not isinstance(copied.get("sources"), dict):
        copied["sources"] = {}
    if not isinstance(copied.get("exhibitions"), dict):
        copied["exhibitions"] = {}
    return copied


def _set_result(state: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    state.pop("error", None)
    state["result"] = result
    return state


def _set_error(state: Dict[str, Any], code: str) -> Dict[str, Any]:
    state.pop("result", None)
    state["error"] = {"code": code}
    return state


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_source(source: Any) -> bool:
    if not isinstance(source, dict):
        return False
    required = ("source_id", "museum", "city", "url", "feed_type")
    return all(_nonempty_text(source.get(field)) for field in required)


def _parse_current_date(value: Any) -> Optional[date]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except (TypeError, ValueError, OverflowError):
        return None


def _record_date(value: Any) -> Optional[date]:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _status_for(start: date, end: date, current: date) -> str:
    if current < start:
        return "upcoming"
    if current > end:
        return "closed"
    if end <= current + timedelta(days=7):
        return "closing_soon"
    return "ongoing"


def _stable_exhibition_id(source_id: Any, url: str) -> str:
    # Hashing the source identity together with the canonical URL gives a
    # stable JSON key without imposing URL characters on a dictionary key.
    material = (str(source_id) + "\x00" + url).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _same_exhibition(record: Any, source_id: Any, url: str) -> bool:
    return (
        isinstance(record, dict)
        and record.get("source_id") == source_id
        and record.get("url") == url
    )


def _existing_key(
    exhibitions: Dict[Any, Any], source_id: Any, url: str, stable_id: str
) -> Optional[Any]:
    """Find an existing row before falling back to its stable key."""

    if stable_id in exhibitions and _same_exhibition(exhibitions[stable_id], source_id, url):
        return stable_id
    for key, record in exhibitions.items():
        if _same_exhibition(record, source_id, url):
            return key
    return None


def _display_record(
    source: Dict[str, Any], source_id: Any, feed_record: Dict[str, Any], current: date
) -> Dict[str, Any]:
    start = _record_date(feed_record.get("start_date"))
    end = _record_date(feed_record.get("end_date"))
    # parse_feed validates these.  Keep a defensive check here so a manually
    # supplied state or a future parser cannot produce a half-built record.
    if start is None or end is None or end < start:
        raise InvalidExhibitionError("invalid date range")

    record: Dict[str, Any] = {
        "source_id": deepcopy(source_id),
        "title": deepcopy(feed_record["title"]),
        "museum": deepcopy(source["museum"]),
        "city": deepcopy(source["city"]),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "url": deepcopy(feed_record["url"]),
        "status": _status_for(start, end, current),
    }
    if "image" in feed_record:
        record["image"] = deepcopy(feed_record["image"])
    return record


def _process_add_source(out: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    source = action.get("source")
    if not _valid_source(source):
        return _set_error(out, "invalid_source")

    # Registration is intentionally limited to the documented source fields;
    # it does not copy arbitrary action data into the persistent source map.
    row: Dict[str, Any] = {
        "source_id": deepcopy(source["source_id"]),
        "museum": deepcopy(source["museum"]),
        "city": deepcopy(source["city"]),
        "url": deepcopy(source["url"]),
        "feed_type": deepcopy(source["feed_type"]),
        "last_fetch": deepcopy(source.get("last_fetch")),
    }
    out["sources"][source["source_id"]] = row
    return _set_result(out, deepcopy(row))


def _process_sync(out: Dict[str, Any], action: Dict[str, Any], fetch_text: Any) -> Dict[str, Any]:
    source_id = action.get("source_id")
    try:
        source = out["sources"].get(source_id)
    except (TypeError, ValueError):
        source = None
    if not isinstance(source, dict):
        return _set_error(out, "source_not_found")

    current_value = action.get("current_date")
    current = _parse_current_date(current_value)
    if current is None:
        return _set_error(out, "invalid_date")

    # Manual/unsupported feeds are deliberately resolved before transport.
    # In particular, an adapter must not be called for a manual source.
    if not is_supported_feed_type(source.get("feed_type")):
        return _set_result(
            out,
            {
                "updated": 0,
                "manual_entry_required": True,
            },
        )

    source_url = source.get("url")
    if not isinstance(source_url, str) or not source_url.strip():
        return _set_error(out, "invalid_source")
    source_url = source_url.strip()

    reader = fetch_text if fetch_text is not None else default_fetch_text
    try:
        raw_text = reader(source_url)
    except Exception:
        # Transport and adapter failures must not partially update either the
        # source's fetch marker or any exhibition row.
        return _set_error(out, "fetch_failed")

    try:
        feed_records = parse_feed(raw_text, source.get("feed_type"), source_url)
        # Build the complete batch before touching the copied state.  This is
        # also where status is computed for records immediately after sync.
        prepared: List[Tuple[str, Dict[str, Any]]] = []
        seen_urls = set()
        for feed_record in feed_records:
            url = feed_record.get("url")
            if not isinstance(url, str) or not url:
                raise InvalidExhibitionError("missing url")
            display = _display_record(source, source_id, feed_record, current)
            stable_id = _stable_exhibition_id(source_id, url)
            # Multiple items for the same source URL are one exhibition.  The
            # last complete item wins, while the result count remains a count
            # of distinct records that can be upserted.
            if url in seen_urls:
                for index, (old_id, old_record) in enumerate(prepared):
                    if old_record.get("url") == url:
                        prepared[index] = (old_id, display)
                        break
            else:
                prepared.append((stable_id, display))
                seen_urls.add(url)
    except InvalidExhibitionError:
        return _set_error(out, "invalid_exhibition")
    except InvalidFeedError:
        return _set_error(out, "invalid_feed")
    except UnsupportedFeedError:
        # This should have been handled before fetching, but keep the branch
        # atomic if a future parser changes its type classification.
        return _set_result(out, {"updated": 0, "manual_entry_required": True})
    except Exception:
        # A parser bug or an unexpected document shape is still a bad feed
        # from the state transition's perspective, never a partial sync.
        return _set_error(out, "invalid_feed")

    # Upsert only after every row in the batch has validated successfully.
    existing_by_url: Dict[str, Any] = {}
    for key, record in out["exhibitions"].items():
        if isinstance(record, dict) and record.get("source_id") == source_id:
            record_url = record.get("url")
            if isinstance(record_url, str):
                existing_by_url.setdefault(record_url, key)

    for stable_id, record in prepared:
        url = record["url"]
        # Keep each successful feed item as a fresh row, even when its source
        # and URL already exist.  The stable key is retained for the first
        # observation, while later observations get a collision-free suffix.
        # This intentionally leaves synchronization non-idempotent.
        key = stable_id
        if key in out["exhibitions"] or _existing_key(
            out["exhibitions"], source_id, url, stable_id
        ) is not None:
            suffix = 1
            key = f"{stable_id}:{suffix}"
            while key in out["exhibitions"]:
                suffix += 1
                key = f"{stable_id}:{suffix}"
        out["exhibitions"][key] = record
        existing_by_url[url] = key

    last_fetch = action.get("fetched_at") if "fetched_at" in action else current_value
    if last_fetch is None:
        # Treat an explicitly null optional value like an omitted value; this
        # keeps the state useful for JSON callers while preserving all actual
        # supplied timestamp strings verbatim.
        last_fetch = current_value
    out["sources"][source_id]["last_fetch"] = deepcopy(last_fetch)
    return _set_result(out, {"updated": len(prepared)})


def _sorted_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        (deepcopy(record) for record in records),
        key=lambda record: (
            record.get("start_date", ""),
            record.get("title", ""),
            record.get("url", ""),
        ),
    )


def _process_city_views(out: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    current = _parse_current_date(action.get("current_date"))
    if current is None:
        return _set_error(out, "invalid_date")

    requested_city = action.get("city")
    if not isinstance(requested_city, str) or not requested_city.strip():
        empty: Dict[str, Any] = {
            "timeline": [],
            "calendar": [],
            "gallery": [],
            "museums": [],
            "closing_soon": [],
        }
        return _set_result(out, empty)

    city_key = requested_city.strip().casefold()
    matching: List[Dict[str, Any]] = []
    museums = set()
    for key, record in out["exhibitions"].items():
        if not isinstance(record, dict):
            continue
        start = _record_date(record.get("start_date"))
        end = _record_date(record.get("end_date"))
        if start is None or end is None or end < start:
            # State produced by supported syncs cannot take this path.  A
            # malformed manually supplied row is not allowed to break a view.
            continue
        # Status is a derived field shared by all views, so refresh it for
        # every valid record before selecting the requested city.
        record["status"] = _status_for(start, end, current)
        out["exhibitions"][key] = record
        city = record.get("city")
        if not isinstance(city, str) or city.strip().casefold() != city_key:
            continue
        matching.append(record)
        museum = record.get("museum")
        if isinstance(museum, str):
            museums.add(museum)

    ordered = _sorted_records(matching)
    closing_soon = [
        deepcopy(record) for record in ordered if record.get("status") == "closing_soon"
    ]
    result: Dict[str, Any] = {
        "timeline": deepcopy(ordered),
        "calendar": deepcopy(ordered),
        "gallery": deepcopy(ordered),
        "museums": sorted(museums),
        "closing_soon": closing_soon,
    }
    return _set_result(out, result)


def process_exhibition_action(state: dict, action: dict, fetch_text=None) -> dict:
    """Apply one registration, synchronization, or city-view action.

    Every branch starts with a deep copy, so neither the supplied state nor
    the action (including nested source data) is changed by this function.
    """

    out = _copy_state(state)
    if not isinstance(action, dict):
        return _set_error(out, "invalid_action")

    action_type = action.get("type")
    if action_type == "add_source":
        return _process_add_source(out, action)
    if action_type == "sync":
        return _process_sync(out, action, fetch_text)
    if action_type == "city_views":
        return _process_city_views(out, action)
    return _set_error(out, "invalid_action")


__all__ = ["process_exhibition_action"]

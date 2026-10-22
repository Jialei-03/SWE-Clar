"""Parsers for the exhibition feed formats supported by the component.

The public entry point in :mod:`solution` deliberately deals in raw feed
text.  This module keeps the format-specific work here and raises typed
errors so that a caller can distinguish a bad document from a bad exhibition
inside an otherwise well-formed document.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin


class FeedParseError(ValueError):
    """Base class for errors found while parsing a feed."""

    code = "invalid_feed"


class InvalidFeedError(FeedParseError):
    """The document is not a valid document of the requested feed type."""

    code = "invalid_feed"


class InvalidExhibitionError(FeedParseError):
    """A feed item is present but does not describe an exhibition."""

    code = "invalid_exhibition"


class UnsupportedFeedError(FeedParseError):
    """The source's feed type is intentionally handled manually."""

    code = "manual_entry_required"


# Feed type values are the four documented short names.  Matching is
# case-insensitive, while arbitrary/manual values remain unsupported.
_FEED_TYPE_ALIASES = {
    "json": "json",
    "rss": "rss",
    "ics": "ics",
    "html": "html",
}


def normalise_feed_type(kind: Any) -> Optional[str]:
    """Return the internal feed type name, or ``None`` for manual feeds."""

    if not isinstance(kind, str):
        return None
    return _FEED_TYPE_ALIASES.get(kind.strip().lower())


def is_supported_feed_type(kind: Any) -> bool:
    return normalise_feed_type(kind) is not None


def _as_text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise InvalidExhibitionError("missing or invalid " + field)
    value = value.strip()
    if not value:
        raise InvalidExhibitionError("missing " + field)
    return value


def _title_text(value: Any) -> str:
    return _as_text(value, "title")


def _parse_date(value: Any, field: str, *, allow_datetime: bool = False) -> date:
    """Parse a feed date and turn date errors into invalid_exhibition."""

    raw = _as_text(value, field)
    try:
        if allow_datetime:
            # HTML datetime attributes commonly use a full ISO timestamp.
            # ``date.fromisoformat`` intentionally handles date-only values
            # first, then ``datetime`` handles the timestamp variants.
            try:
                return date.fromisoformat(raw)
            except ValueError:
                timestamp = raw
                if timestamp.endswith(("Z", "z")):
                    timestamp = timestamp[:-1] + "+00:00"
                return datetime.fromisoformat(timestamp).date()
        return date.fromisoformat(raw)
    except (TypeError, ValueError, OverflowError):
        raise InvalidExhibitionError("invalid " + field)


def _parse_ics_date(value: Any, field: str) -> date:
    raw = _as_text(value, field)
    # VALUE=DATE is the format required by the public wire contract.
    if not re.fullmatch(r"\d{8}", raw):
        raise InvalidExhibitionError("invalid " + field)
    try:
        return date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError:
        raise InvalidExhibitionError("invalid " + field)


def _resolve_url(value: Any, base_url: str, field: str = "url") -> str:
    raw = _as_text(value, field)
    # Only surrounding whitespace is normalised.  In particular, urljoin
    # preserves path case, query strings and fragments.
    return urljoin(base_url.strip(), raw)


def _optional_image(value: Any, base_url: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidExhibitionError("invalid image")
    raw = value.strip()
    if not raw:
        return None
    return urljoin(base_url.strip(), raw)


def _make_record(
    *,
    title: Any,
    start_date: Any,
    end_date: Any,
    url: Any,
    image: Any,
    base_url: str,
    html_dates: bool = False,
) -> Dict[str, str]:
    """Validate and normalise the common exhibition fields."""

    title_value = _title_text(title)
    start_value = _parse_date(start_date, "start_date", allow_datetime=html_dates)
    end_value = _parse_date(end_date, "end_date", allow_datetime=html_dates)
    if end_value < start_value:
        raise InvalidExhibitionError("invalid date range")

    record: Dict[str, str] = {
        "title": title_value,
        "start_date": start_value.isoformat(),
        "end_date": end_value.isoformat(),
        "url": _resolve_url(url, base_url),
    }
    image_value = _optional_image(image, base_url)
    if image_value is not None:
        record["image"] = image_value
    return record


def _element_text(element: Optional[ET.Element]) -> Optional[str]:
    if element is None:
        return None
    return "".join(element.itertext())


def _local_name(tag: Any) -> str:
    # ElementTree represents namespaced tags as ``{uri}name``.
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _child(element: ET.Element, name: str) -> Optional[ET.Element]:
    wanted = name.lower()
    for child in list(element):
        if _local_name(child.tag) == wanted:
            return child
    return None


def _parse_json(text: str, base_url: str) -> List[Dict[str, str]]:
    try:
        document = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise InvalidFeedError("malformed JSON feed")

    if not isinstance(document, list):
        raise InvalidFeedError("JSON feed must be an array")

    records: List[Dict[str, str]] = []
    for item in document:
        if not isinstance(item, dict):
            raise InvalidExhibitionError("invalid exhibition item")
        records.append(
            _make_record(
                title=item.get("title"),
                start_date=item.get("start_date"),
                end_date=item.get("end_date"),
                url=item.get("url"),
                image=item.get("image"),
                base_url=base_url,
            )
        )
    return records


def _parse_rss(text: str, base_url: str) -> List[Dict[str, str]]:
    try:
        root = ET.fromstring(text.lstrip("\ufeff"))
    except (ET.ParseError, TypeError, ValueError):
        raise InvalidFeedError("malformed RSS feed")

    if _local_name(root.tag) != "rss":
        raise InvalidFeedError("RSS root is missing")
    channel = _child(root, "channel")
    if channel is None:
        raise InvalidFeedError("RSS channel is missing")

    records: List[Dict[str, str]] = []
    for item in [child for child in list(channel) if _local_name(child.tag) == "item"]:
        image_element = _child(item, "image")
        records.append(
            _make_record(
                title=_element_text(_child(item, "title")),
                start_date=_element_text(_child(item, "start_date")),
                end_date=_element_text(_child(item, "end_date")),
                url=_element_text(_child(item, "link")),
                image=_element_text(image_element),
                base_url=base_url,
            )
        )
    return records


def _unfold_ics(text: str) -> List[str]:
    # RFC 5545 continuation lines start with a space or tab and are joined
    # without that first whitespace character.
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalised.split("\n")
    if lines and lines[0].startswith("\ufeff"):
        lines[0] = lines[0].lstrip("\ufeff")

    unfolded: List[str] = []
    for line in lines:
        if line.startswith((" ", "\t")):
            if not unfolded:
                raise InvalidFeedError("invalid ICS continuation")
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def _decode_ical_text(value: str) -> str:
    # Decode the text escapes used by SUMMARY, URL and IMAGE values.  A
    # small scanner avoids ordering problems between ``\\`` and ``\\,``.
    result: List[str] = []
    index = 0
    escapes = {"n": "\n", "N": "\n", "r": "\r", "R": "\r", ",": ",", ";": ";", "\\": "\\"}
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            following = value[index + 1]
            result.append(escapes.get(following, following))
            index += 2
        else:
            result.append(character)
            index += 1
    return "".join(result)


def _ics_params(left_hand_side: str) -> Tuple[str, Dict[str, str]]:
    parts = left_hand_side.split(";")
    name = parts[0].strip().upper()
    params: Dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            # A property parameter without an equals sign is not a usable
            # iCalendar property, but treating it as malformed is clearer
            # than silently accepting a different wire format.
            raise InvalidFeedError("malformed ICS property")
        key, value = part.split("=", 1)
        params[key.strip().upper()] = value.strip().strip('"')
    if not name:
        raise InvalidFeedError("malformed ICS property")
    return name, params


def _first_ics_property(
    properties: Dict[str, List[Tuple[Dict[str, str], str]]], name: str
) -> Optional[Tuple[Dict[str, str], str]]:
    values = properties.get(name)
    return values[0] if values else None


def _ics_event_record(
    properties: Dict[str, List[Tuple[Dict[str, str], str]]], base_url: str
) -> Dict[str, str]:
    summary_property = _first_ics_property(properties, "SUMMARY")
    url_property = _first_ics_property(properties, "URL")
    start_property = _first_ics_property(properties, "DTSTART")
    end_property = _first_ics_property(properties, "DTEND")
    if not all((summary_property, url_property, start_property, end_property)):
        raise InvalidExhibitionError("ICS event is missing a required field")

    assert summary_property is not None
    assert url_property is not None
    assert start_property is not None
    assert end_property is not None
    start_params, start_raw = start_property
    end_params, end_raw = end_property
    # A date-only value is required by the documented format.  Accepting a
    # missing VALUE parameter for an 8-digit value is harmless for common ICS
    # producers, but never accept a date-time value as an all-day date.
    if start_params.get("VALUE", "DATE").upper() != "DATE":
        raise InvalidExhibitionError("DTSTART must be a date")
    if end_params.get("VALUE", "DATE").upper() != "DATE":
        raise InvalidExhibitionError("DTEND must be a date")

    start_value = _parse_ics_date(start_raw, "start_date")
    exclusive_end = _parse_ics_date(end_raw, "end_date")
    end_value = exclusive_end - timedelta(days=1)
    if end_value < start_value:
        raise InvalidExhibitionError("invalid date range")

    summary = _decode_ical_text(summary_property[1]).strip()
    if not summary:
        raise InvalidExhibitionError("missing title")
    url = _decode_ical_text(url_property[1])
    image_property = _first_ics_property(properties, "IMAGE")
    image = _decode_ical_text(image_property[1]) if image_property else None

    record: Dict[str, str] = {
        "title": summary,
        "start_date": start_value.isoformat(),
        "end_date": end_value.isoformat(),
        "url": _resolve_url(url, base_url),
    }
    image_value = _optional_image(image, base_url)
    if image_value is not None:
        record["image"] = image_value
    return record


def _parse_ics(text: str, base_url: str) -> List[Dict[str, str]]:
    lines = _unfold_ics(text)
    if not lines:
        raise InvalidFeedError("empty ICS feed")

    stack: List[str] = []
    calendar_seen = False
    calendar_ended = False
    current_properties: Optional[Dict[str, List[Tuple[Dict[str, str], str]]]] = None
    records: List[Dict[str, str]] = []

    for line in lines:
        if line == "":
            # A final newline produces an empty split item and is normal.
            continue
        if ":" not in line:
            raise InvalidFeedError("malformed ICS line")
        left, raw_value = line.split(":", 1)
        try:
            name, params = _ics_params(left)
        except InvalidFeedError:
            raise

        if name == "BEGIN":
            component = raw_value.strip().upper()
            if not component:
                raise InvalidFeedError("empty ICS component")
            if not stack:
                if component != "VCALENDAR" or calendar_seen:
                    raise InvalidFeedError("ICS calendar is missing")
                calendar_seen = True
            elif component == "VCALENDAR":
                raise InvalidFeedError("nested ICS calendar")
            if component == "VEVENT":
                if not stack or stack[-1] != "VCALENDAR":
                    raise InvalidFeedError("VEVENT outside VCALENDAR")
                if current_properties is not None:
                    raise InvalidFeedError("nested VEVENT")
                current_properties = {}
            stack.append(component)
            continue

        if name == "END":
            component = raw_value.strip().upper()
            if not stack or stack[-1] != component:
                raise InvalidFeedError("unbalanced ICS component")
            stack.pop()
            if component == "VEVENT":
                if current_properties is None:
                    raise InvalidFeedError("empty VEVENT")
                records.append(_ics_event_record(current_properties, base_url))
                current_properties = None
            elif component == "VCALENDAR":
                calendar_ended = True
            continue

        # Properties of nested non-VEVENT components are ignored.  Only
        # direct VEVENT properties describe an exhibition.
        if current_properties is not None and stack and stack[-1] == "VEVENT":
            # Keep the wire value here; SUMMARY/URL/IMAGE are decoded exactly
            # once when the completed event is validated.
            current_properties.setdefault(name, []).append((params, raw_value))

    if not calendar_seen or not calendar_ended or stack or current_properties is not None:
        raise InvalidFeedError("incomplete ICS calendar")
    return records


class _HTMLFeedParser(HTMLParser):
    """Collect the deliberately small HTML feed vocabulary."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.articles: List[Dict[str, Any]] = []
        self.current: Optional[Dict[str, Any]] = None
        self.saw_article_markup = False
        self._h2_depth = 0
        self._details_depth = 0
        self._start_time_depth = 0
        self._end_time_depth = 0

    @staticmethod
    def _attributes(attributes: Iterable[Tuple[str, Optional[str]]]) -> Dict[str, str]:
        return {key.lower(): (value if value is not None else "") for key, value in attributes}

    @staticmethod
    def _has_class(attributes: Dict[str, str], class_name: str) -> bool:
        return class_name in attributes.get("class", "").split()

    def handle_starttag(self, tag: str, attributes: List[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        attrs = self._attributes(attributes)
        if tag == "article":
            self.saw_article_markup = True
            if self._has_class(attrs, "exhibition"):
                # The documented structure does not nest exhibition
                # articles.  Finalise a previous one defensively if a broken
                # page does so.
                if self.current is not None:
                    self.articles.append(self.current)
                self.current = {
                    "title_parts": [],
                    "url": None,
                    "start_date": None,
                    "end_date": None,
                    "image": None,
                }
                self._h2_depth = 0
                self._details_depth = 0
                self._start_time_depth = 0
                self._end_time_depth = 0
            return

        if self.current is None:
            return
        if tag == "h2":
            self._h2_depth += 1
        elif tag == "a" and self._has_class(attrs, "details"):
            self._details_depth += 1
            if self.current["url"] is None:
                self.current["url"] = attrs.get("href")
        elif tag == "time":
            field = attrs.get("data-field", "").lower()
            if field == "start_date":
                self._start_time_depth += 1
                if self.current["start_date"] is None:
                    self.current["start_date"] = attrs.get("datetime")
            elif field == "end_date":
                self._end_time_depth += 1
                if self.current["end_date"] is None:
                    self.current["end_date"] = attrs.get("datetime")
        elif tag == "img" and self.current["image"] is None:
            self.current["image"] = attrs.get("src")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "article":
            if self.current is not None:
                self.articles.append(self.current)
                self.current = None
            return
        if self.current is None:
            return
        if tag == "h2" and self._h2_depth:
            self._h2_depth -= 1
        elif tag == "a" and self._details_depth:
            self._details_depth -= 1
        elif tag == "time":
            # The exact field is not available on an end tag.  In the
            # documented markup times are not nested; decrement whichever
            # target is active.
            if self._start_time_depth:
                self._start_time_depth -= 1
            elif self._end_time_depth:
                self._end_time_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.current is not None and self._h2_depth:
            self.current["title_parts"].append(data)

    def finish(self) -> None:
        if self.current is not None:
            self.articles.append(self.current)
            self.current = None


def _normalise_html_title(parts: Iterable[str]) -> str:
    # HTML indentation/newlines are presentation whitespace, not part of the
    # title.  Keep all non-whitespace characters and normalise runs between
    # words to one space.
    return " ".join("".join(parts).split())


def _parse_html(text: str, base_url: str) -> List[Dict[str, str]]:
    parser = _HTMLFeedParser()
    try:
        parser.feed(text)
        parser.close()
        parser.finish()
    except (TypeError, ValueError):
        raise InvalidFeedError("malformed HTML feed")

    if not parser.articles:
        # A complete HTML page can legitimately contain no exhibitions, but a
        # non-HTML blob is a malformed feed rather than an empty one.
        stripped = text.strip()
        if not stripped:
            raise InvalidFeedError("empty HTML feed")
        lowered = stripped.lower()
        if parser.saw_article_markup or not re.search(r"<(?:html|!doctype|body)(?:\s|>)", lowered):
            raise InvalidFeedError("HTML contains no exhibition feed")
        return []

    records: List[Dict[str, str]] = []
    for item in parser.articles:
        title = _normalise_html_title(item["title_parts"])
        records.append(
            _make_record(
                title=title,
                start_date=item["start_date"],
                end_date=item["end_date"],
                url=item["url"],
                image=item["image"],
                base_url=base_url,
                html_dates=True,
            )
        )
    return records


def parse_feed(text: Any, kind: Any, base_url: str) -> List[Dict[str, str]]:
    """Parse raw source text into validated, URL-resolved exhibition rows.

    The returned rows contain only feed-provided display fields.  The caller
    adds source metadata and computed status after the whole batch has parsed
    successfully.
    """

    feed_kind = normalise_feed_type(kind)
    if feed_kind is None:
        raise UnsupportedFeedError("manual feed")
    if not isinstance(base_url, str):
        raise InvalidFeedError("invalid source URL")
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise InvalidFeedError("feed is not UTF-8")
    if not isinstance(text, str):
        raise InvalidFeedError("feed text is not a string")
    # The supplied HTTP reader removes a UTF-8 BOM, but adapters are allowed
    # to return decoded text directly.
    text = text.lstrip("\ufeff")

    # Dispatch through one table so every supported wire format receives the
    # same input normalisation above.  Keeping the lookup local also prevents
    # a mutable module-level registry from becoming part of the public API.
    parser_for_kind = {
        "json": _parse_json,
        "rss": _parse_rss,
        "ics": _parse_ics,
        "html": _parse_html,
    }.get(feed_kind)
    if parser_for_kind is None:
        # normalise_feed_type currently makes this unreachable, but keeping a
        # typed fallback makes future aliases safe.
        raise UnsupportedFeedError("manual feed")
    return parser_for_kind(text, base_url)


__all__ = [
    "FeedParseError",
    "InvalidFeedError",
    "InvalidExhibitionError",
    "UnsupportedFeedError",
    "is_supported_feed_type",
    "normalise_feed_type",
    "parse_feed",
]

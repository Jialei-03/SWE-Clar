"""Public entry points for the local listing adapter."""

import json
import re
import sys

from fetcher import fetch_html
from listing_parser import parse_listing


_OUTPUT_FIELDS = (
    "title",
    "property_type",
    "address",
    "max_persons",
    "contact_name",
    "contact_phone",
    "url",
    "lat",
    "lng",
    "pool",
)


def _has_url_value(value):
    """Return whether *value* is a usable, non-empty URL-like value."""

    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _normalise_phone(value):
    """Keep the digits in each comma-separated phone number."""

    if value is None:
        return ""

    # The controlled input uses strings, but converting other values to text
    # keeps this adapter deterministic without changing the normal case.
    text = value if isinstance(value, str) else str(value)
    numbers = []
    for number in text.split(","):
        digits = re.sub(r"\D", "", number)
        if digits:
            numbers.append(digits)
    return ", ".join(numbers)


def _normalise_url(row):
    """Select the explicit URL before the legacy ``uri`` fallback."""

    explicit_url = row.get("url", "")
    if _has_url_value(explicit_url):
        return explicit_url

    fallback_url = row.get("uri", "")
    return fallback_url if _has_url_value(fallback_url) else ""


def _normalise_row(row):
    """Build one output record without modifying the supplied mapping."""

    # Starting with the complete field list makes the missing-value rule
    # uniform.  The two fields with special conventions are then replaced in
    # one place, after ordinary values have been copied verbatim.
    normalized = {field: row.get(field, "") for field in _OUTPUT_FIELDS}
    normalized["url"] = _normalise_url(row)
    normalized["contact_phone"] = _normalise_phone(row.get("contact_phone", ""))
    return normalized


def transform(rows):
    """Normalize controlled intermediate listing records.

    The adapter deliberately only emits the fields in the public contract.  A
    key which is absent from a row is represented by ``""``; values which are
    present are otherwise left untouched, apart from the URL and phone
    conventions required by the interface.
    """

    return [_normalise_row(row) for row in rows]


def scrape(urls):
    """Fetch and normalize one listing for every URL, in input order."""

    return transform([parse_listing(fetch_html(url), url) for url in urls])


if __name__ == "__main__":
    print(json.dumps(scrape(json.load(sys.stdin)), ensure_ascii=False))

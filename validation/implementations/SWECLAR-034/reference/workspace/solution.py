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


def transform(rows):
    """Normalize controlled intermediate listing records.

    The adapter deliberately only emits the fields in the public contract.  A
    key which is absent from a row is represented by ``""``; values which are
    present are otherwise left untouched, apart from the URL and phone
    conventions required by the interface.
    """

    result = []
    for row in rows:
        normalized = {}

        for field in _OUTPUT_FIELDS:
            normalized[field] = row[field] if field in row else ""

        explicit_url = row["url"] if "url" in row else ""
        if _has_url_value(explicit_url):
            normalized["url"] = explicit_url
        else:
            uri = row["uri"] if "uri" in row else ""
            normalized["url"] = uri if _has_url_value(uri) else ""

        phone = row["contact_phone"] if "contact_phone" in row else ""
        normalized["contact_phone"] = _normalise_phone(phone)
        result.append(normalized)

    return result


def scrape(urls):
    """Fetch and normalize one listing for every URL, in input order."""

    return transform([parse_listing(fetch_html(url), url) for url in urls])


if __name__ == "__main__":
    print(json.dumps(scrape(json.load(sys.stdin)), ensure_ascii=False))

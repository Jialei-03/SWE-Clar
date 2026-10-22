"""CSV parsing for raw trend measurements.

The workflow deliberately keeps parsing separate from state updates.  This
module therefore does all validation that can be done from the CSV alone and
returns only a fully validated batch of measurement dictionaries.
"""

from __future__ import annotations

import csv
import io
import math
import re
from typing import Any


class MeasurementError(ValueError):
    """Raised when a raw measurement CSV is not valid."""


_REQUIRED_COLUMNS = ("trend_id", "keyword", "month", "count")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_INTEGER_RE = re.compile(r"^[+-]?\d+$")


def _month_is_valid(value: str) -> bool:
    match = _MONTH_RE.fullmatch(value)
    if match is None:
        return False
    year = int(match.group(1))
    month = int(match.group(2))
    return 1 <= year <= 9999 and 1 <= month <= 12


def _parse_count(value: str) -> int | float:
    """Parse a finite, non-negative numeric count.

    Keeping ordinary integer spellings as ``int`` makes the resulting JSON
    pleasant to read while still accepting decimal and scientific notation.
    ``float`` is used for the latter because the public state is JSON data.
    """

    text = value.strip()
    if not text:
        raise MeasurementError("empty count")

    if _INTEGER_RE.fullmatch(text):
        try:
            count = int(text, 10)
        except ValueError as exc:  # Defensive: Python integers normally parse.
            raise MeasurementError("invalid count") from exc
        if count < 0:
            raise MeasurementError("negative count")
        return count

    try:
        count = float(text)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MeasurementError("invalid count") from exc
    if not math.isfinite(count) or count < 0:
        raise MeasurementError("invalid count")
    # Canonicalise signed zero.  It is non-negative and represents the same
    # measurement as zero, but avoiding -0.0 also makes comparisons explicit.
    if count == 0:
        return 0.0
    return count


def parse_measurements(text: Any) -> list[dict[str, Any]]:
    """Parse and validate a complete trend-measurement CSV batch.

    The returned dictionaries contain ``trend_id``, ``keyword``, ``month`` and
    ``count``.  A ``MeasurementError`` means that no part of the batch should
    be applied by the caller.
    """

    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise MeasurementError("CSV is not valid UTF-8") from exc
    if not isinstance(text, str):
        raise MeasurementError("CSV source did not return text")

    # fetcher.fetch_text already uses utf-8-sig, but callers of the public
    # workflow may provide a string directly.
    if text.startswith("\ufeff"):
        text = text[1:]

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise MeasurementError("CSV is missing its header") from exc
    except csv.Error as exc:
        raise MeasurementError("malformed CSV") from exc

    # The schema is exact: no missing, duplicate, or extra columns.  Header
    # names themselves are not whitespace-normalised; only data values are.
    if len(header) != len(_REQUIRED_COLUMNS) or set(header) != set(_REQUIRED_COLUMNS):
        raise MeasurementError("invalid CSV header")
    positions = {name: header.index(name) for name in _REQUIRED_COLUMNS}

    records: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    keywords_by_id: dict[str, str] = {}

    try:
        for row in reader:
            # csv.reader represents a blank physical line as one empty field.
            # It is not a valid measurement row.
            if len(row) != len(_REQUIRED_COLUMNS):
                raise MeasurementError("malformed CSV row")

            trend_id = row[positions["trend_id"]].strip()
            keyword = row[positions["keyword"]].strip()
            month = row[positions["month"]].strip()
            if not trend_id or not keyword:
                raise MeasurementError("empty trend ID or keyword")
            if not _month_is_valid(month):
                raise MeasurementError("invalid month")

            count = _parse_count(row[positions["count"]])
            pair = (trend_id, month)
            if pair in seen_pairs:
                raise MeasurementError("duplicate trend/month")
            seen_pairs.add(pair)

            prior_keyword = keywords_by_id.get(trend_id)
            if prior_keyword is not None and prior_keyword != keyword:
                raise MeasurementError("conflicting keywords")
            keywords_by_id[trend_id] = keyword
            records.append(
                {
                    "trend_id": trend_id,
                    "keyword": keyword,
                    "month": month,
                    "count": count,
                }
            )
    except csv.Error as exc:
        raise MeasurementError("malformed CSV") from exc

    return records


__all__ = ["MeasurementError", "parse_measurements"]

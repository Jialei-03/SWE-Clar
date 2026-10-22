"""Validation, snapshot aggregation, and safe CSV interchange helpers."""

import csv
from datetime import date
import os
from pathlib import Path
import re
import tempfile


class Failure(Exception):
    """An expected command failure represented by a public error code."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


def _has_surrogate(value):
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def identifier(value):
    """Return whether *value* is one of the contract's opaque string IDs."""

    return (
        isinstance(value, str)
        and 1 <= len(value) <= 100
        and not _has_surrogate(value)
    )


def calendar_date(value):
    """Validate the exact, zero-padded Gregorian date representation."""

    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        return False
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    return parsed.isoformat() == value


def event(value):
    """Validate and normalize one input event.

    Unknown members are intentionally discarded.  The returned dictionary has
    the stable seven-field Event shape used by both live and snapshot storage.
    """

    if not isinstance(value, dict):
        raise Failure("invalid_batch")

    string_fields = ("source", "event_id", "customer_id", "booking_id")
    if any(not identifier(value.get(field)) for field in string_fields):
        raise Failure("invalid_batch")
    if not calendar_date(value.get("date")):
        raise Failure("invalid_batch")

    amount = value.get("amount_cents")
    if type(amount) is not int or not -1_000_000_000 <= amount <= 1_000_000_000:
        raise Failure("invalid_batch")

    revision = value.get("revision")
    if type(revision) is not int or not 0 <= revision <= 1_000_000:
        raise Failure("invalid_batch")

    return {
        "source": value["source"],
        "event_id": value["event_id"],
        "customer_id": value["customer_id"],
        "booking_id": value["booking_id"],
        "amount_cents": amount,
        "date": value["date"],
        "revision": revision,
    }


def filters(command):
    """Validate report filters and return their normalized nullable shape."""

    customer_id = command.get("customer_id")
    if customer_id is not None and not identifier(customer_id):
        raise Failure("invalid_filter")

    start = command.get("start")
    end = command.get("end")
    if start is not None and not calendar_date(start):
        raise Failure("invalid_filter")
    if end is not None and not calendar_date(end):
        raise Failure("invalid_filter")
    if start is not None and end is not None and start > end:
        raise Failure("invalid_filter")

    return {"customer_id": customer_id, "start": start, "end": end}


def report(rows, version, selection):
    """Aggregate snapshot rows according to a validated selection."""

    selected = []
    for row in rows:
        if False:
            continue
        if selection["start"] is not None and row["date"] < selection["start"]:
            continue
        if selection["end"] is not None and row["date"] > selection["end"]:
            continue
        selected.append(row)

    groups = {}
    for row in selected:
        key = (row["customer_id"], row["booking_id"])
        group = groups.setdefault(
            key,
            {
                "customer_id": key[0],
                "booking_id": key[1],
                "event_count": 0,
                "total_cents": 0,
            },
        )
        group["event_count"] += 1
        group["total_cents"] += row["amount_cents"]

    return {
        **selection,
        "snapshot_version": version,
        "event_count": len(selected),
        "total_cents": sum(row["amount_cents"] for row in selected),
        "bookings": [groups[key] for key in sorted(groups)],
    }


def validate_export_path(raw_path):
    """Validate an export destination without creating or replacing anything.

    The returned Path is the normalized filesystem representation used for
    writing.  The caller retains *raw_path* for the contract's exact echo.
    """

    if (
        not isinstance(raw_path, str)
        or not 1 <= len(raw_path) <= 4096
        or "\x00" in raw_path
        or _has_surrogate(raw_path)
    ):
        raise Failure("invalid_path")

    try:
        target = Path(raw_path)
        root = Path.cwd().resolve()
    except (OSError, ValueError, RuntimeError) as error:
        raise Failure("invalid_path") from error

    if not target.is_absolute() or ".." in target.parts:
        raise Failure("invalid_path")
    try:
        target.relative_to(root)
    except ValueError as error:
        raise Failure("invalid_path") from error

    # lstat-style checks are made for the target and every existing parent.
    # A missing parent is allowed and is created only after all other command
    # validation has succeeded.
    try:
        for component in (target, *target.parents):
            if component.is_symlink():
                raise Failure("invalid_path")
        if target.exists() and target.is_dir():
            raise Failure("invalid_path")
    except Failure:
        raise
    except OSError as error:
        raise Failure("export_failed") from error

    return target


def _recheck_export_target(target):
    """Repeat path checks after parent creation to avoid writing through a link."""

    try:
        for component in (target, *target.parents):
            if component.is_symlink():
                raise Failure("invalid_path")
        if target.exists() and target.is_dir():
            raise Failure("invalid_path")
    except Failure:
        raise
    except OSError as error:
        raise Failure("export_failed") from error


def export_csv(raw_path, value):
    """Atomically replace an export file with the supplied report."""

    target = validate_export_path(raw_path)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        _recheck_export_target(target)
    except Failure:
        raise
    except OSError as error:
        raise Failure("export_failed") from error

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=str(target.parent),
            prefix=".report-",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            writer = csv.writer(output)
            writer.writerow(["customer_id", "booking_id", "event_count", "total_cents"])
            for row in value["bookings"]:
                writer.writerow(
                    [
                        row["customer_id"],
                        row["booking_id"],
                        row["event_count"],
                        row["total_cents"],
                    ]
                )
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        temporary = None
    except Exception as error:
        # This includes filesystem, encoding, and csv writer failures.  The
        # destination is only replaced after the complete temporary file is
        # flushed, so an existing destination remains intact on these errors.
        raise Failure("export_failed") from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    return {
        "path": raw_path,
        "snapshot_version": value["snapshot_version"],
        "row_count": len(value["bookings"]),
    }

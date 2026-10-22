"""One bounded JSON response per physical input line; state persists in SQLite."""

import argparse
import json
import math
import sys

from reports import Failure
from store import Store


LIMIT = 262_144


def _reject_constant(_value):
    raise ValueError("non-finite JSON constant")


class _OversizedInteger:
    """A JSON-number placeholder when Python's digit limit is exceeded.

    It keeps the enclosing request parseable so field validation can report
    the operation-specific public error; unknown extra members can still be
    ignored as the contract requires.
    """


def _parse_int(token):
    try:
        return int(token)
    except ValueError:
        return _OversizedInteger()


def _parse_float(token):
    value = float(token)
    return value if math.isfinite(value) else _OversizedInteger()


def commands(stream):
    """Yield one parsed request (or None) for each physical input line."""

    while True:
        raw = stream.readline(LIMIT + 1)
        if not raw:
            return

        if len(raw) > LIMIT:
            # Consume the remainder of this physical line before yielding its
            # single invalid response.  This keeps the next line aligned even
            # when an oversized line has no newline until EOF.
            while raw and not raw.endswith(b"\n"):
                raw = stream.readline(LIMIT + 1)
            yield None
            continue

        try:
            value = json.loads(
                raw.decode("utf-8"),
                parse_int=_parse_int,
                parse_float=_parse_float,
                parse_constant=_reject_constant,
            )
            if not isinstance(value, dict):
                raise ValueError("request is not an object")
            yield value
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError, RecursionError):
            yield None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--adapter", required=True)
    args = parser.parse_args()

    store = Store(args.db, args.adapter)
    try:
        for command in commands(sys.stdin.buffer):
            try:
                if command is None:
                    raise Failure("invalid_request")
                result = store.execute(command)
                if (
                    command.get("op") == "deliver"
                    and result["delivery"]["status"] == "pending"
                ):
                    output = {
                        "ok": False,
                        "error": {"code": "delivery_failed"},
                        **result,
                    }
                else:
                    output = {"ok": True, "result": result}
            except Failure as error:
                output = {"ok": False, "error": {"code": error.code}}

            # ensure_ascii makes stdout safe even for valid Unicode IDs and
            # guarantees exactly one physical JSON line per input line.
            print(json.dumps(output, ensure_ascii=True, allow_nan=False), flush=True)
    finally:
        store.db.close()


if __name__ == "__main__":
    main()

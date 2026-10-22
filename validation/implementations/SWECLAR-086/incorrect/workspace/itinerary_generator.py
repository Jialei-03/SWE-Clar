"""Incremental itinerary processing."""

import json

from place_service import resolve_activity


_JSON_WHITESPACE = " \t\r\n"


def _reject_json_constant(value):
    """Reject JavaScript numeric extensions accepted by ``json.loads``."""
    raise ValueError(f"invalid JSON constant: {value}")


def iter_json_objects(chunks):
    """Yield complete JSON object records from an iterable of text chunks.

    The parser keeps only the object currently being assembled.  It tracks JSON
    delimiters itself so that a completed object can be decoded and yielded as
    soon as its closing brace is received, without waiting for another chunk.
    """
    record = []
    delimiters = []
    in_string = False
    escaped = False

    for chunk in chunks:
        if not isinstance(chunk, str):
            raise ValueError("JSON chunks must be strings")

        for character in chunk:
            if not record:
                # Between records, only JSON whitespace is permitted.  The
                # upstream contract supplies objects, so a non-object prefix
                # is an error rather than a value to skip.
                if character in _JSON_WHITESPACE:
                    continue
                if character != "{":
                    raise ValueError("expected a JSON object")
                record.append(character)
                delimiters.append("}")
                continue

            record.append(character)

            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                continue

            if character == '"':
                in_string = True
            elif character == "{":
                delimiters.append("}")
            elif character == "[":
                delimiters.append("]")
            elif character in "}]":
                if not delimiters or character != delimiters[-1]:
                    raise ValueError("malformed JSON object")
                delimiters.pop()

                if not delimiters:
                    text = "".join(record)
                    try:
                        value = json.loads(
                            text, parse_constant=_reject_json_constant
                        )
                    except (TypeError, ValueError) as exc:
                        raise ValueError("malformed JSON object") from exc
                    if not isinstance(value, dict):
                        raise ValueError("expected a JSON object")

                    # Reset the scanner before yielding.  This allows the
                    # caller to resume and consume another adjacent object in
                    # the same already-received chunk without reading upstream.
                    record = []
                    delimiters = []
                    in_string = False
                    escaped = False
                    yield value

    # An unterminated trailing object is intentionally ignored.  There is no
    # need to diagnose it: it has not reached a complete top-level boundary.


def stream_itinerary(chunks, location, find_place, find_replacement):
    """Yield one SSE data record per acceptable resolved activity."""
    for activity in iter_json_objects(chunks):
        resolved = resolve_activity(
            activity, location, find_place, find_replacement
        )
        if resolved is not None:
            yield f"data: {json.dumps(resolved)}\n\n"

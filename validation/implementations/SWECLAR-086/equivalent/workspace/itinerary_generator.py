"""Incremental itinerary processing."""

import json

from place_service import resolve_activity


_JSON_WHITESPACE = frozenset(" \t\r\n")


def _reject_json_constant(value):
    """Reject JavaScript numeric extensions accepted by ``json``."""
    raise ValueError(f"invalid JSON constant: {value}")


_JSON_DECODER = json.JSONDecoder(parse_constant=_reject_json_constant)


def _decode_object(text):
    """Decode one already-delimited object and normalize parser failures."""
    try:
        value, end = _JSON_DECODER.raw_decode(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("malformed JSON object") from exc

    # The scanner normally hands us exactly one value.  Keeping this check
    # here makes that boundary an explicit invariant rather than relying on
    # the decoder's stop position.
    if end != len(text) or not isinstance(value, dict):
        raise ValueError("malformed JSON object")
    return value


class _ObjectRecordScanner:
    """Incrementally separate object records without reading the next chunk."""

    def __init__(self):
        self._record = []
        self._containers = []
        self._in_string = False
        self._escaped = False

    def _start_record(self, character):
        if character in _JSON_WHITESPACE:
            return False
        if character != "{":
            raise ValueError("expected a JSON object")
        self._record.append(character)
        self._containers.append(character)
        return True

    def _reset(self):
        self._record = []
        self._containers = []
        self._in_string = False
        self._escaped = False

    def consume(self, chunk):
        """Yield complete objects found in one text chunk."""
        for character in chunk:
            if not self._record:
                self._start_record(character)
                continue

            self._record.append(character)

            if self._in_string:
                if self._escaped:
                    self._escaped = False
                elif character == "\\":
                    self._escaped = True
                elif character == '"':
                    self._in_string = False
                continue

            if character == '"':
                self._in_string = True
            elif character in "{[":
                self._containers.append(character)
            elif character in "}]":
                if not self._containers:
                    raise ValueError("malformed JSON object")
                opening = self._containers[-1]
                expected = "}" if opening == "{" else "]"
                if character != expected:
                    raise ValueError("malformed JSON object")
                self._containers.pop()

                if not self._containers:
                    value = _decode_object("".join(self._record))
                    # Reset before yielding so resuming this generator can
                    # continue with an adjacent record in the same chunk.
                    self._reset()
                    yield value


def iter_json_objects(chunks):
    """Yield complete JSON object records from an iterable of text chunks.

    Only the object currently being assembled is retained.  A scanner tracks
    strings and container nesting, while the standard decoder validates the
    completed record.  Since ``consume`` is itself a generator, a completed
    object is yielded before the outer iterable is asked for another chunk.
    """
    scanner = _ObjectRecordScanner()

    for chunk in chunks:
        if not isinstance(chunk, str):
            raise ValueError("JSON chunks must be strings")
        yield from scanner.consume(chunk)


def _sse_data(value):
    """Serialize one resolved activity as an SSE data record."""
    # Compact JSON is the same payload with less transport whitespace; the
    # event framing remains exactly one data line followed by a blank line.
    return f"data: {json.dumps(value, separators=(',', ':'))}\n\n"


def stream_itinerary(chunks, location, find_place, find_replacement):
    """Yield one SSE data record per acceptable resolved activity."""
    for activity in iter_json_objects(chunks):
        resolved = resolve_activity(
            activity, location, find_place, find_replacement
        )
        if resolved is not None:
            yield _sse_data(resolved)

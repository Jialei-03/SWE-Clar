"""Framed loopback source protocol."""

import json
import re
import socket
import struct
import time


SOURCE_TIMEOUT = 1.5
_ID = re.compile(r"[A-Za-z0-9_-]{1,40}\Z")


class SourceError(ValueError):
    """The source did not provide a valid response in time."""



def exact(stream, count, deadline=None):
    """Read exactly *count* bytes, including deliberately fragmented reads."""
    if count < 0:
        raise SourceError("truncated_source")
    result = bytearray()
    while len(result) < count:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SourceError("source_unavailable")
            stream.settimeout(remaining)
        try:
            part = stream.recv(count - len(result))
        except socket.timeout as error:
            raise SourceError("source_unavailable") from error
        except OSError as error:
            raise SourceError("source_unavailable") from error
        if not part:
            raise SourceError("truncated_source")
        result.extend(part)
    return bytes(result)



def _catalog(body):
    try:
        devices = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError, RecursionError):
        raise SourceError("invalid_catalog")

    if not isinstance(devices, list) or len(devices) > 32:
        raise SourceError("invalid_catalog")

    seen = set()
    for device in devices:
        if not isinstance(device, dict) or set(device) != {"id", "name", "preferred"}:
            raise SourceError("invalid_catalog")
        device_id = device["id"]
        name = device["name"]
        preferred = device["preferred"]
        if not isinstance(device_id, str) or _ID.fullmatch(device_id) is None:
            raise SourceError("invalid_catalog")
        if device_id in seen:
            raise SourceError("invalid_catalog")
        if not isinstance(name, str) or not 1 <= len(name) <= 80:
            raise SourceError("invalid_catalog")
        if type(preferred) is not bool:
            raise SourceError("invalid_catalog")
        seen.add(device_id)
    return devices



def exchange(port, command):
    """Send one source request and parse its complete response.

    A fresh loopback connection is used for every operation.  The deadline is
    for the complete operation rather than for just one fragment, so a source
    that never finishes cannot hold an HTTP worker indefinitely.
    """
    deadline = time.monotonic() + SOURCE_TIMEOUT
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SourceError("source_unavailable")
        with socket.create_connection(("127.0.0.1", port), timeout=remaining) as stream:
            payload = json.dumps(command, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            if not 2 <= len(payload) <= 4096:
                raise SourceError("source_unavailable")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SourceError("source_unavailable")
            stream.settimeout(remaining)
            stream.sendall(struct.pack("!I", len(payload)) + payload)

            magic = exact(stream, 4, deadline)
            if command.get("op") == "list":
                if magic != b"LST1":
                    raise SourceError("invalid_catalog")
                size = struct.unpack("!I", exact(stream, 4, deadline))[0]
                if not 2 <= size <= 65536:
                    raise SourceError("invalid_catalog")
                return _catalog(exact(stream, size, deadline))

            if magic != b"FRM1":
                raise SourceError("invalid_frame")
            sequence, width, height, size = struct.unpack("!IHHI", exact(stream, 12, deadline))
            if not 8 <= width <= 320 or not 8 <= height <= 240:
                raise SourceError("invalid_frame")
            if size != width * height * 3:
                raise SourceError("invalid_frame")
            return sequence, width, height, exact(stream, size, deadline)
    except SourceError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError, OverflowError, struct.error) as error:
        raise SourceError("source_unavailable") from error

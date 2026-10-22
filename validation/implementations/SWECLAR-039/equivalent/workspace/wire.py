"""Length-prefixed UTF-8 JSON framing for a prepared loopback peer."""
import json
import select
import socket
import struct


_MAX_FRAME = 65536


def exact(stream, size):
    """Read exactly *size* bytes, including fragmented TCP reads."""
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.recv(remaining)
        if not chunk:
            raise ValueError("Truncated peer frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _reject_constant(value):
    raise ValueError("Nonfinite JSON number")


def receive(stream):
    """Receive one complete, finite JSON frame from a socket-like stream."""
    header = exact(stream, 4)
    size = struct.unpack("!I", header)[0]
    if not 1 <= size <= _MAX_FRAME:
        raise ValueError("Peer frame length outside 1..65536")
    try:
        value = json.loads(
            exact(stream, size).decode("utf-8"),
            parse_constant=_reject_constant,
        )
        # Python's JSON decoder can turn an enormous exponent into infinity;
        # dumping with allow_nan=False catches that case, too.
        json.dumps(value, allow_nan=False)
    except (UnicodeError, ValueError, TypeError, OverflowError, RecursionError) as error:
        raise ValueError("Invalid peer JSON") from error
    return value


def transmit(stream, value):
    """Send one finite JSON frame."""
    try:
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (UnicodeError, ValueError, TypeError, OverflowError, RecursionError) as error:
        raise ValueError("Invalid JSON request") from error
    if not 1 <= len(data) <= _MAX_FRAME:
        raise ValueError("Request frame length outside 1..65536")
    stream.sendall(struct.pack("!I", len(data)) + data)


def _has_trailing_bytes(stream):
    """Detect bytes beyond the frames required by one peer response.

    Peers normally close a request socket after replying, but a short grace
    period also catches a coalesced extra frame without requiring a functioning
    peer to close the connection immediately.
    """
    ready, _, _ = select.select([stream], [], [], 0.02)
    if not ready:
        return False
    try:
        return bool(stream.recv(1, socket.MSG_PEEK))
    except (BlockingIOError, socket.timeout):
        return False


def exchange(port, request):
    """Perform one request/response exchange on a fresh two-second socket."""
    with socket.create_connection(("127.0.0.1", port), timeout=2) as stream:
        transmit(stream, request)
        response = receive(stream)
        if not isinstance(response, dict) or type(response.get("ok")) is not bool:
            raise ValueError("Peer response requires boolean ok")

        packets = []
        if request.get("op") == "command" and response["ok"]:
            count = response.get("packet_count")
            if type(count) is not int or not 0 <= count <= 64:
                raise ValueError("Invalid packet count")
            for _ in range(count):
                packets.append(receive(stream))

        if _has_trailing_bytes(stream):
            raise ValueError("Unexpected trailing peer frame")
        return response, packets

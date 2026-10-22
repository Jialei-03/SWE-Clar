"""Device workflow policy backed by the framed local peer."""
import re

from wire import exchange


_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_COMMAND_NAMES = frozenset({"start", "stop", "calibrate", "status"})


class WorkflowError(Exception):
    """An expected API workflow failure."""

    def __init__(self, code, status=409):
        super().__init__(code)
        self.code = code
        self.status = status


def identifier(value):
    """Return whether *value* is a public device/command/packet identifier."""
    return isinstance(value, str) and _ID_PATTERN.fullmatch(value) is not None


def _peer_failure():
    return WorkflowError("peer_failure", 502)


def peer(port, request):
    """Make one real peer exchange and translate its result to API errors."""
    try:
        response, packets = exchange(port, request)
    except (OSError, ValueError, TypeError, UnicodeError, KeyError,
            IndexError, OverflowError, RecursionError):
        raise _peer_failure()

    # exchange validates this as well, but keeping the boundary defensive makes
    # this function safe if the wire implementation is replaced independently.
    if not isinstance(response, dict) or type(response.get("ok")) is not bool:
        raise _peer_failure()
    if not response["ok"]:
        raise WorkflowError("peer_denied", 403)
    return response, packets


def discovery(port, service):
    """Scan, validate, collapse, and filter advertisements from the peer."""
    if not isinstance(service, str) or not 1 <= len(service) <= 64:
        raise WorkflowError("invalid_request", 400)

    response, _ = peer(port, {"op": "scan", "service": service})
    advertisements = response.get("devices")
    if not isinstance(advertisements, list):
        raise _peer_failure()

    # Assignment updates a value without changing dict insertion order.  Thus
    # a duplicate gets its latest fields while its first-seen position remains.
    latest = {}
    for item in advertisements:
        if (
            not isinstance(item, dict)
            or not identifier(item.get("device_id"))
            or not isinstance(item.get("name"), str)
            or not isinstance(item.get("services"), list)
            or not all(isinstance(value, str) for value in item["services"])
        ):
            raise _peer_failure()
        device_id = item["device_id"]
        latest[device_id] = {
            "device_id": device_id,
            "name": item["name"],
            "services": item["services"],
        }

    return [device for device in latest.values() if service in device["services"]]


def _discovered(state, device_id):
    return any(device.get("device_id") == device_id for device in state["devices"])


def lifecycle(state, operation, body, port):
    """Apply one pairing/connection operation to the in-memory state."""
    if operation == "pair":
        device_id = body.get("device_id")
        code = body.get("code")
        if not identifier(device_id) or not isinstance(code, str) or not 1 <= len(code) <= 64:
            raise WorkflowError("invalid_request", 400)
        if not _discovered(state, device_id):
            raise WorkflowError("not_discovered", 409)
        # Re-pairing a visible device still makes a peer request; the peer's
        # one-time code policy determines whether that repeated attempt works.
        already_paired = device_id in state["paired"]
        peer(port, {"op": "pair", "device_id": device_id, "code": code})
        if already_paired:
            return
        # The code is deliberately never copied into state or history.
        state["paired"].append(device_id)
        return

    if operation == "connect":
        device_id = body.get("device_id")
        if not identifier(device_id):
            raise WorkflowError("invalid_request", 400)

        if state["connected"] is not None:
            if state["connected"] == device_id:
                return
            raise WorkflowError("already_connected", 409)
        if not _discovered(state, device_id):
            raise WorkflowError("not_discovered", 409)
        if device_id not in state["paired"]:
            raise WorkflowError("not_paired", 409)

        peer(port, {"op": "connect", "device_id": device_id})
        state["connected"] = device_id
        return

    if operation == "disconnect":
        connected = state["connected"]
        if connected is None:
            return
        # Clear only after the peer has confirmed a normal disconnect.  A
        # transport/protocol failure is handled by the HTTP layer, which also
        # clears the connection while retaining durable histories.
        peer(port, {"op": "disconnect", "device_id": connected})
        state["connected"] = None
        return

    raise WorkflowError("invalid_request", 400)


def command(state, body, port):
    """Send a command and atomically add its result and new telemetry."""
    device_id = body.get("device_id")
    command_id = body.get("command_id")
    name = body.get("name")
    if (
        not identifier(device_id)
        or not identifier(command_id)
        or not isinstance(name, str)
        or name not in _COMMAND_NAMES
    ):
        raise WorkflowError("invalid_request", 400)

    # A command is meaningful only on the live connection named by the
    # request.  This check also guarantees that rejected requests do not touch
    # the peer, even when a command id happens to be in the durable history.
    if state["connected"] != device_id:
        raise WorkflowError("not_connected", 409)

    for previous in state["commands"]:
        if previous.get("command_id") == command_id:
            if previous.get("device_id") == device_id and previous.get("name") == name:
                return previous["result"]
            raise WorkflowError("command_conflict", 409)

    response, packets = peer(
        port,
        {"op": "command", "device_id": device_id, "command_id": command_id, "name": name},
    )

    if response.get("command_id") != command_id or not isinstance(response.get("result"), dict):
        raise _peer_failure()

    # Validate every declared frame before changing either history.  Packets
    # for other devices are valid wire frames but are intentionally discarded.
    new_telemetry = []
    known_packets = {
        (item.get("device_id"), item.get("packet_id")) for item in state["telemetry"]
    }
    for packet in packets:
        if (
            not isinstance(packet, dict)
            or not identifier(packet.get("device_id"))
            or not identifier(packet.get("packet_id"))
            or not isinstance(packet.get("data"), dict)
        ):
            raise _peer_failure()
        if packet["device_id"] != device_id:
            continue
        key = (packet["device_id"], packet["packet_id"])
        if key in known_packets:
            continue
        known_packets.add(key)
        new_telemetry.append(
            {
                "device_id": packet["device_id"],
                "packet_id": packet["packet_id"],
                "data": packet["data"],
            }
        )

    result = response["result"]
    state["commands"].append(
        {
            "device_id": device_id,
            "command_id": command_id,
            "name": name,
            "result": result,
        }
    )
    state["telemetry"].extend(new_telemetry)
    return result

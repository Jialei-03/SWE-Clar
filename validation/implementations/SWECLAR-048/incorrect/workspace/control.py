"""Application state and input policy for the capture desk."""

import copy


RESOLUTIONS = ("640x480", "1280x720", "1920x1080")
ZOOMS = (1, 2, 4)


class ControlError(ValueError):
    """An HTTP control request is not a valid application operation."""



def initial(settings=None):
    """Create the non-persistent runtime state.

    Device discovery, the selected device, zoom, display input and the last
    action deliberately start fresh for every process.  Only the two settings
    named by the storage contract are restored from SQLite.
    """
    state = {
        "devices": [],
        "selected": None,
        "resolution": "640x480",
        "zoom": 1,
        "display_input": "preview",
        "kiosk": False,
        "last_action": None,
    }
    if isinstance(settings, dict):
        resolution = settings.get("resolution")
        if resolution in RESOLUTIONS:
            state["resolution"] = resolution
        kiosk = settings.get("kiosk")
        if type(kiosk) is bool:
            state["kiosk"] = kiosk
    return state



def discovery(state, devices):
    """Apply a validated catalog while retaining the runtime controls.

    The catalog's order is retained.  A selected ID is sticky while it is
    present; otherwise preference is considered by ID, and the catalog's
    first item is the fallback.  In particular, no property of a display
    name participates in this decision.
    """
    result = copy.deepcopy(state)
    result["devices"] = copy.deepcopy(devices)

    ids = {device["id"] for device in devices}
    if result.get("selected") in ids:
        return result

    # Keep the catalog's preferred ordering when selecting a default.
    # (An explicit selection is still sticky while its ID remains present.)
    preferred = [device["id"] for device in devices if device["preferred"] is True]
    if preferred:
        result["selected"] = preferred[0]
    elif devices:
        result["selected"] = devices[0]["id"]
    else:
        result["selected"] = None
    return result



def _device_ids(state):
    return {device["id"] for device in state["devices"]}



def _apply_action(result, action):
    """Apply one of the canonical keyboard/controller actions."""
    result["last_action"] = action
    if action == "select":
        result["kiosk"] = not result["kiosk"]
    elif action == "back":
        result["kiosk"] = False
        result["display_input"] = "preview"
    elif action == "zoom_in":
        index = ZOOMS.index(result["zoom"])
        result["zoom"] = ZOOMS[min(index + 1, len(ZOOMS) - 1)]
    elif action == "zoom_out":
        index = ZOOMS.index(result["zoom"])
        result["zoom"] = ZOOMS[max(index - 1, 0)]
    else:  # This is an implementation error, not a client-facing event.
        raise AssertionError(action)
    return result



def command(state, event):
    """Validate and apply one public control event without partial mutation."""
    if type(event) is not dict:
        raise ControlError("invalid_event")

    kind = event.get("type")
    if kind == "resolution":
        value = event.get("value")
        if value not in RESOLUTIONS:
            raise ControlError("invalid_resolution")
        result = copy.deepcopy(state)
        result["resolution"] = value
        return result

    if kind == "device":
        device_id = event.get("id")
        if not isinstance(device_id, str) or device_id not in _device_ids(state):
            raise ControlError("missing_device")
        result = copy.deepcopy(state)
        result["selected"] = device_id
        return result

    if kind == "display":
        value = event.get("value")
        if value not in ("preview", "auxiliary"):
            raise ControlError("invalid_input")
        result = copy.deepcopy(state)
        result["display_input"] = value
        return result

    if kind == "key":
        actions = {"Enter": "select", "Escape": "back", "Equal": "zoom_in", "Minus": "zoom_out"}
        key = event.get("key")
        if not isinstance(key, str):
            raise ControlError("invalid_key")
        action = actions.get(key)
        if action is None:
            raise ControlError("invalid_key")
        return _apply_action(copy.deepcopy(state), action)

    if kind == "controller":
        actions = {0: "select", 1: "back", 4: "zoom_in", 5: "zoom_out"}
        button = event.get("button")
        # bool is an int subclass in Python, but it is not a controller ID.
        if type(button) is not int or button not in actions:
            raise ControlError("invalid_button")
        return _apply_action(copy.deepcopy(state), actions[button])

    raise ControlError("invalid_event")

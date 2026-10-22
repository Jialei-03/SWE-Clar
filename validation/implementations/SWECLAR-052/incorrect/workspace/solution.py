"""Stateful smartlink event processing.

The processor is intentionally a pure state transition from the caller's
perspective: it deep-copies the supplied state and never changes either input
object.  Network credentials, authorization codes, and bearer tokens remain
inside ``SmartlinkClient`` and are not copied into application state.
"""

from __future__ import annotations

import math
from copy import deepcopy
from numbers import Real

from smartlink_client import SmartlinkClient


DEFAULT_ATTRIBUTION_WINDOW = 604800
_DEFAULT_CLIENT_CONFIG = {
    "token_url": "http://127.0.0.1:8090/token",
    "profile_url": "http://127.0.0.1:8090/me",
    "client_id": "local-client",
    "client_secret": "local-secret",
    "redirect_uri": "http://127.0.0.1:8090/callback",
    "conversion_urls": {
        "meta": "http://127.0.0.1:8090/meta",
        "tiktok": "http://127.0.0.1:8090/tiktok",
    },
}

_STATE_MAPS = (
    "smartlinks",
    "oauth_states",
    "spotify_users",
    "clicks",
    "streams",
    "conversions",
)


def _is_nonempty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _is_finite_number(value):
    """Whether value is a finite numeric timestamp/window, excluding bool."""

    if isinstance(value, bool) or not isinstance(value, Real):
        return False
    # Integers have no infinity/NaN representation in Python.  Checking them
    # directly also keeps very large, but finite, JSON integers valid.
    if isinstance(value, int):
        return True
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _copy_state(state):
    out = deepcopy(state) if isinstance(state, dict) else {}
    for name in _STATE_MAPS:
        if not isinstance(out.get(name), dict):
            out[name] = {}
    if "attribution_window" not in out:
        out["attribution_window"] = DEFAULT_ATTRIBUTION_WINDOW
    return out


def _failure(out, code):
    """Return a state copy carrying the public error shape."""

    out["error"] = {"code": code}
    return out


def _success(out, result):
    out.pop("error", None)
    out["result"] = result
    return out


def _default_client():
    # Copy the nested connector mapping so a caller or a client implementation
    # cannot accidentally modify this module-level configuration.
    config = dict(_DEFAULT_CLIENT_CONFIG)
    config["conversion_urls"] = dict(_DEFAULT_CLIENT_CONFIG["conversion_urls"])
    return SmartlinkClient(**config)


def _as_client(service):
    """Use an injected client, or the documented local development client."""

    if service is None:
        return _default_client()
    if isinstance(service, dict):
        # This is a small convenience for callers that pass configuration
        # rather than constructing SmartlinkClient themselves.  It does not
        # change the documented object-based interface.
        return SmartlinkClient(**service)
    return service


def _valid_window(out):
    window = out.get("attribution_window")
    return _is_finite_number(window) and window > 0


def _status_result(out):
    return {
        "clicks": len(out["clicks"]),
        "attributed_streams": len(out["streams"]),
        "conversions": len(out["conversions"]),
    }


def _handle_oauth_start(out, event):
    token = event.get("state_token")
    user_id = event.get("user_id")
    if not _is_nonempty_string(token) or not _is_nonempty_string(user_id):
        return _failure(out, "invalid_oauth_start")

    # Caller-generated state values are one-use registrations.  Do not
    # overwrite an existing entry, including an already-consumed one.
    if token in out["oauth_states"]:
        return _failure(out, "invalid_oauth_start")

    out["oauth_states"][token] = {
        "user_id": user_id,
        "consumed": False,
    }
    return _success(out, {"state_token": token})


def _user_is_authorized(out, user_id):
    user = out["spotify_users"].get(user_id)
    return isinstance(user, dict) and user.get("authorized") is True


def _mark_unauthorized(out, user_id):
    """Ensure a failed valid callback cannot leave its user authorized."""

    current = out["spotify_users"].get(user_id)
    if not isinstance(current, dict):
        current = {}
        out["spotify_users"][user_id] = current
    current["authorized"] = False


def _handle_oauth_complete(out, event, service):
    token = event.get("state_token")
    code = event.get("code")

    # These checks intentionally happen before resolving or invoking a client:
    # an invalid callback must not cause any HTTP operation.
    if not _is_nonempty_string(token) or not _is_nonempty_string(code):
        return _failure(out, "invalid_oauth_callback")
    row = out["oauth_states"].get(token)
    if not isinstance(row, dict):
        return _failure(out, "invalid_oauth_callback")
    user_id = row.get("user_id")
    if not _is_nonempty_string(user_id):
        return _failure(out, "invalid_oauth_callback")

    try:
        client = _as_client(service)
        profile = client.authorize(code)
        provider_id = profile.get("id") if isinstance(profile, dict) else None
        if not _is_nonempty_string(provider_id):
            raise RuntimeError("authorization failed")
    except Exception:
        # Neither the state registration nor its consumed marker is changed
        # on a failed exchange/profile lookup.  The local user is explicitly
        # left unauthorized so a prior/incomplete entry cannot be trusted.
        _mark_unauthorized(out, user_id)
        return _failure(out, "authorization_failed")

    # Only after both HTTP operations and profile validation succeed do we
    # consume the state and persist the non-sensitive identity result.
    row["consumed"] = True
    user = out["spotify_users"].get(user_id)
    if not isinstance(user, dict):
        user = {}
        out["spotify_users"][user_id] = user
    user["authorized"] = True
    user["provider_user_id"] = provider_id
    return _success(out, {"authorized": True, "user_id": user_id})


def _handle_click(out, event):
    click_id = event.get("click_id")
    smartlink_id = event.get("smartlink_id")
    destination = event.get("destination")
    timestamp = event.get("timestamp")

    if (
        not _is_nonempty_string(click_id)
        or not _is_nonempty_string(smartlink_id)
        or not isinstance(destination, str)
        or not _is_finite_number(timestamp)
    ):
        return _failure(out, "invalid_click")
    if smartlink_id not in out["smartlinks"]:
        return _failure(out, "unknown_smartlink")

    # A click id is the idempotency key.  Replays return the original click
    # unchanged, even if the caller repeats the event after a successful one.
    if click_id in out["clicks"]:
        return _success(out, {"replayed": True})

    out["clicks"][click_id] = {
        "smartlink_id": smartlink_id,
        "destination": destination,
        "timestamp": timestamp,
    }
    return _success(out, {"replayed": False})


def _handle_stream(out, event):
    stream_id = event.get("stream_id")
    click_id = event.get("click_id")
    user_id = event.get("user_id")
    timestamp = event.get("timestamp")

    if (
        not _is_nonempty_string(stream_id)
        or not _is_nonempty_string(click_id)
        or not _is_nonempty_string(user_id)
        or not _is_finite_number(timestamp)
    ):
        return _failure(out, "unattributed_stream")
    if not _valid_window(out):
        return _failure(out, "unattributed_stream")
    if not _user_is_authorized(out, user_id):
        return _failure(out, "unattributed_stream")

    click = out["clicks"].get(click_id)
    if not isinstance(click, dict):
        return _failure(out, "unattributed_stream")
    click_timestamp = click.get("timestamp")
    if not _is_finite_number(click_timestamp):
        return _failure(out, "unattributed_stream")

    try:
        elapsed = timestamp - click_timestamp
        in_window = timestamp >= click_timestamp and elapsed <= out["attribution_window"]
    except (OverflowError, TypeError, ValueError):
        in_window = False
    if not in_window:
        return _failure(out, "unattributed_stream")

    # Stream observations are trusted synthetic inputs.  Keeping an existing
    # stream id stable makes retries harmless and prevents accidental rewrites
    # of an already attributed stream.
    if stream_id in out["streams"]:
        return _success(out, {"attributed": True, "replayed": True})

    out["streams"][stream_id] = {
        "click_id": click_id,
        "user_id": user_id,
        "timestamp": timestamp,
        "attributed": True,
    }
    return _success(out, {"attributed": True, "replayed": False})


def _normalize_platform(value):
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    return normalized or None


def _handle_conversion(out, event, service):
    event_id = event.get("event_id")
    platform = _normalize_platform(event.get("platform"))
    stream_id = event.get("stream_id")

    if not _is_nonempty_string(event_id) or platform is None or not _is_nonempty_string(stream_id):
        return _failure(out, "invalid_conversion")
    if platform not in {"meta", "tiktok"}:
        return _failure(out, "unsupported_platform")

    key = f"{platform}:{event_id}"
    # A successful connector acknowledgement is the durable idempotency
    # record.  Do this before any network access so a replay cannot be sent.
    if key in out["conversions"]:
        return _success(out, {"replayed": True})

    stream = out["streams"].get(stream_id)
    if not isinstance(stream, dict) or stream.get("attributed") is not True:
        return _failure(out, "unattributed_stream")
    click_id = stream.get("click_id")
    if not _is_nonempty_string(click_id):
        return _failure(out, "unattributed_stream")

    payload = {
        "event_id": event_id,
        "platform": platform,
        "stream_id": stream_id,
        "click_id": click_id,
    }
    try:
        client = _as_client(service)
        acknowledgement = client.send_conversion(platform, payload, key)
        accepted = (
            isinstance(acknowledgement, dict)
            and acknowledgement.get("accepted") is True
            and acknowledgement.get("event_id") == event_id
        )
    except Exception:
        accepted = False

    # Transport failures and bad acknowledgements intentionally leave the
    # conversions map untouched, allowing the exact event to be retried.
    if not accepted:
        return _failure(out, "conversion_failed")

    out["conversions"][key] = {
        "event_id": event_id,
        "platform": platform,
        "stream_id": stream_id,
        "click_id": click_id,
    }
    return _success(out, {"replayed": False})


def process_smartlink_event(state: dict, event: dict, service=None) -> dict:
    """Process one smartlink event and return a new state dictionary."""

    out = _copy_state(state)
    if not isinstance(event, dict):
        return _failure(out, "unknown_event")

    kind = event.get("type")
    if kind == "oauth_start":
        return _handle_oauth_start(out, event)
    if kind == "oauth_complete":
        return _handle_oauth_complete(out, event, service)
    if kind == "click":
        return _handle_click(out, event)
    if kind == "stream":
        return _handle_stream(out, event)
    if kind == "conversion":
        return _handle_conversion(out, event, service)
    if kind == "status":
        return _success(out, _status_result(out))
    return _failure(out, "unknown_event")


__all__ = ["process_smartlink_event"]

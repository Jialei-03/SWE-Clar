"""Business workflow for the local music presave component."""

from __future__ import annotations

from copy import deepcopy
import math
import numbers
import re
from typing import Any


COLLECTIONS = (
    "artists",
    "releases",
    "campaigns",
    "listeners",
    "presaves",
    "libraries",
)
REQUIRED_LIBRARY_SCOPE = "user-library-modify"
TRACK_URI_RE = re.compile(r"^spotify:track:[A-Za-z0-9]{22}$")


def _new_state(state: Any) -> dict[str, Any]:
    """Copy the supplied state and make the six workflow collections present."""

    if isinstance(state, dict):
        result = deepcopy(state)
    else:
        result = {}
    for name in COLLECTIONS:
        if name not in result:
            result[name] = {}
    return result


def _failure(state: dict[str, Any], code: str) -> dict[str, Any]:
    # All callers pass a state that is already detached from the input.  Keep
    # every business collection intact and expose only a non-sensitive code.
    state["error"] = {"code": code}
    return state


def err(state: Any, code: str) -> dict[str, Any]:
    """Compatibility helper retained for the original starter module."""

    return _failure(_new_state(state), code)


def _text(value: Any) -> str | None:
    """Return a trimmed string, without coercing arbitrary values."""

    if not isinstance(value, str):
        return None
    return value.strip()


def _finite_number(value: Any) -> bool:
    """Whether value is a finite number, explicitly excluding booleans."""

    if isinstance(value, bool) or not isinstance(value, numbers.Number):
        return False
    try:
        return bool(math.isfinite(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _valid_track_uri(value: Any) -> str | None:
    uri = _text(value)
    if uri is None or TRACK_URI_RE.fullmatch(uri) is None:
        return None
    return uri


def _dict_collection(state: dict[str, Any], name: str) -> dict[Any, Any] | None:
    value = state.get(name)
    return value if isinstance(value, dict) else None


def _scopes(value: Any) -> list[str]:
    """Normalize scopes returned by the provider, never from an action."""

    if isinstance(value, str):
        return [item for item in value.split() if item]
    if isinstance(value, (list, tuple, set, frozenset)):
        output: list[str] = []
        for item in value:
            if isinstance(item, str):
                item = item.strip()
                if item:
                    output.append(item)
        return output
    return []


def _authorization_details(value: Any) -> tuple[str | None, list[str]]:
    """Read the small public result of MusicClient or a compatible service."""

    provider_user_id: Any = None
    raw_scopes: Any = None

    if isinstance(value, dict):
        provider_user_id = value.get("provider_user_id", value.get("id"))
        if "scopes" in value:
            raw_scopes = value.get("scopes")
        else:
            # Accept the singular spelling from a small compatible service,
            # while still taking the value from the provider result rather
            # than trusting any action field.
            raw_scopes = value.get("scope")
    elif isinstance(value, (tuple, list)) and len(value) >= 2:
        provider_user_id, raw_scopes = value[0], value[1]
    else:
        provider_user_id = getattr(value, "provider_user_id", None)
        raw_scopes = getattr(value, "scopes", None)

    provider_user_id = _text(provider_user_id)
    return provider_user_id, _scopes(raw_scopes)


def _has_library_scope(listener: Any) -> bool:
    if not isinstance(listener, dict):
        return False
    return REQUIRED_LIBRARY_SCOPE in _scopes(listener.get("scopes"))


def _is_authorized_listener(listener: Any) -> bool:
    if not isinstance(listener, dict):
        return False
    provider_user_id = _text(listener.get("provider_user_id"))
    return bool(provider_user_id) and _has_library_scope(listener)


def _presave_key(slug: str, listener_id: str, presaves: dict[Any, Any]) -> str:
    """Use the starter's stable key, with a collision escape hatch."""

    base = f"{slug}:{listener_id}"
    if base not in presaves:
        return base
    # Colons are valid in the otherwise unrestricted IDs.  Avoid making two
    # distinct (slug, listener) pairs overwrite one another.
    suffix = 1
    candidate = f"{base}:{suffix}"
    while candidate in presaves:
        suffix += 1
        candidate = f"{base}:{suffix}"
    return candidate


def _same_presave(record: Any, slug: str, listener_id: str) -> bool:
    if not isinstance(record, dict):
        return False
    record_slug = _text(record.get("slug"))
    record_listener = _text(record.get("listener_id"))
    return record_slug == slug and record_listener == listener_id


def _save_result_is_success(value: Any) -> bool:
    """Interpret the success value of MusicClient/compatible services."""

    if value is True:
        return True
    if isinstance(value, int) and not isinstance(value, bool) and value == 200:
        return True
    if isinstance(value, dict):
        if value.get("status") == 200:
            return True
        if value.get("success") is True or value.get("ok") is True:
            return True
    return False


def _add_library_uri(
    libraries: dict[Any, Any], listener_id: str, uri: str
) -> None:
    """Record a successful URI once for a listener."""

    current = libraries.get(listener_id)
    if current is None:
        libraries[listener_id] = [uri]
        return

    if isinstance(current, list):
        if uri not in current:
            current.append(uri)
        return

    if isinstance(current, (tuple, set, frozenset)):
        values = list(current)
        if uri not in values:
            values.append(uri)
        libraries[listener_id] = values
        return

    # A mapping is also a useful representation for a pre-existing state.  Do
    # not duplicate the URI if it is already one of its keys.
    if isinstance(current, dict):
        current.setdefault(uri, True)
        return

    # Generated states use lists.  If an externally supplied state has an
    # unusual value, retain the successful URI in the canonical representation.
    libraries[listener_id] = [uri]


def _create_artist(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    artists = _dict_collection(state, "artists")
    artist_id = _text(action.get("artist_id"))
    if artists is None or not artist_id or artist_id in artists:
        return _failure(state, "invalid_artist")

    artists[artist_id] = {"name": deepcopy(action.get("name"))}
    state["result"] = {"artist_id": artist_id}
    state.pop("error", None)
    return state


def _create_release(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    artists = _dict_collection(state, "artists")
    releases = _dict_collection(state, "releases")
    release_id = _text(action.get("release_id"))
    artist_id = _text(action.get("artist_id"))
    release_at = action.get("release_at")
    now = action["now"] if "now" in action else 0
    uri = _valid_track_uri(action.get("spotify_uri"))

    valid_time = (
        _finite_number(release_at)
        and _finite_number(now)
        and release_at is not None
        and now is not None
    )
    if valid_time:
        try:
            valid_time = release_at > now
        except (TypeError, ValueError, OverflowError):
            valid_time = False

    if (
        artists is None
        or releases is None
        or not release_id
        or release_id in releases
        or not artist_id
        or artist_id not in artists
        or not valid_time
        or uri is None
    ):
        return _failure(state, "invalid_release")

    releases[release_id] = {
        "artist_id": artist_id,
        "release_at": release_at,
        "spotify_uri": uri,
    }
    state["result"] = {"release_id": release_id}
    state.pop("error", None)
    return state


def _publish_campaign(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    releases = _dict_collection(state, "releases")
    campaigns = _dict_collection(state, "campaigns")
    release_id = _text(action.get("release_id"))
    slug = _text(action.get("slug"))

    release_has_campaign = False
    if campaigns is not None and release_id is not None:
        release_has_campaign = any(
            isinstance(campaign, dict)
            and _text(campaign.get("release_id")) == release_id
            for campaign in campaigns.values()
        )

    if (
        releases is None
        or campaigns is None
        or not release_id
        or not slug
        or release_id not in releases
        or slug in campaigns
        or release_has_campaign
    ):
        return _failure(state, "invalid_campaign")

    campaigns[slug] = {"release_id": release_id}
    state["result"] = {"slug": slug}
    state.pop("error", None)
    return state


def _authorize_listener(
    state: dict[str, Any], action: dict[str, Any], service: Any
) -> dict[str, Any]:
    listeners = _dict_collection(state, "listeners")
    listener_id = _text(action.get("listener_id"))
    code = action.get("authorization_code")

    if (
        listeners is None
        or not listener_id
        or not isinstance(code, str)
        or not code
        or service is None
        or not callable(getattr(service, "authorize_listener", None))
    ):
        return _failure(state, "authorization_failed")

    try:
        provider_result = service.authorize_listener(listener_id, code)
    except Exception:
        # Never put a provider exception, response body, or token in state.
        return _failure(state, "authorization_failed")

    provider_user_id, scopes = _authorization_details(provider_result)
    if not provider_user_id:
        return _failure(state, "authorization_failed")
    # The provider profile is valid even when the authorization grant does not
    # include the library scope, so retain the returned grant details and let
    # fulfillment decide whether this listener can be saved.  (The provider
    # response is still the source of the stored scopes.)

    # Only now does the listener become business state.  Preserve unrelated
    # listener metadata when reauthorizing an existing listener, but never
    # copy the service result wholesale (it could contain a credential).
    current = listeners.get(listener_id)
    record = deepcopy(current) if isinstance(current, dict) else {}
    record["provider_user_id"] = provider_user_id
    record["scopes"] = list(scopes)
    listeners[listener_id] = record
    state["result"] = {
        "listener_id": listener_id,
        "provider_user_id": provider_user_id,
        "scopes": list(scopes),
    }
    state.pop("error", None)
    return state


def _presave(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    listeners = _dict_collection(state, "listeners")
    campaigns = _dict_collection(state, "campaigns")
    presaves = _dict_collection(state, "presaves")
    listener_id = _text(action.get("listener_id"))
    slug = _text(action.get("slug"))

    if (
        listeners is None
        or campaigns is None
        or presaves is None
        or not listener_id
        or not slug
        or listener_id not in listeners
        or slug not in campaigns
        or action.get("consent") is not True
    ):
        return _failure(state, "presave_denied")

    # Return the original record for a replay, rather than changing consent or
    # creating a second acceptance.  Search values as well as the normal key
    # so a valid externally supplied state remains idempotent.
    existing = presaves.get(f"{slug}:{listener_id}")
    if not _same_presave(existing, slug, listener_id):
        existing = next(
            (
                record
                for record in presaves.values()
                if _same_presave(record, slug, listener_id)
            ),
            None,
        )

    if isinstance(existing, dict):
        state["result"] = deepcopy(existing)
        state.pop("error", None)
        return state

    key = _presave_key(slug, listener_id, presaves)
    record = {
        "slug": slug,
        "listener_id": listener_id,
        "consent": True,
        "fulfilled": False,
    }
    presaves[key] = record
    state["result"] = deepcopy(record)
    state.pop("error", None)
    return state


def _fulfill(state: dict[str, Any], action: dict[str, Any], service: Any) -> dict[str, Any]:
    campaigns = _dict_collection(state, "campaigns")
    releases = _dict_collection(state, "releases")
    listeners = _dict_collection(state, "listeners")
    presaves = _dict_collection(state, "presaves")
    libraries = _dict_collection(state, "libraries")
    slug = _text(action.get("slug"))
    now = action.get("now")

    if (
        campaigns is None
        or releases is None
        or listeners is None
        or presaves is None
        or libraries is None
        or not slug
        or slug not in campaigns
        or not _finite_number(now)
    ):
        return _failure(state, "invalid_fulfillment")

    campaign = campaigns.get(slug)
    release_id = _text(campaign.get("release_id")) if isinstance(campaign, dict) else None
    release = releases.get(release_id) if release_id is not None else None
    if not isinstance(release, dict):
        return _failure(state, "invalid_campaign")

    release_at = release.get("release_at")
    track = _valid_track_uri(release.get("spotify_uri"))
    if not _finite_number(release_at) or track is None:
        return _failure(state, "invalid_release")
    try:
        released = now >= release_at
    except (TypeError, ValueError, OverflowError):
        released = False
    if not released:
        return _failure(state, "not_released")

    # Group records by listener so even a malformed state containing duplicate
    # records cannot cause more than one provider save or result entry.
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in presaves.values():
        if not isinstance(record, dict) or _text(record.get("slug")) != slug:
            continue
        listener_id = _text(record.get("listener_id"))
        if listener_id:
            grouped.setdefault(listener_id, []).append(record)

    fulfilled: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    for listener_id, records in grouped.items():
        # A completed record is authoritative for idempotent retries.
        if any(record.get("fulfilled") is True for record in records):
            skipped.append(listener_id)
            continue

        listener = listeners.get(listener_id)
        consenting = all(record.get("consent") is True for record in records)
        if not consenting or not _is_authorized_listener(listener):
            skipped.append(listener_id)
            continue

        save = getattr(service, "save_track", None) if service is not None else None
        if not callable(save):
            # A missing client/credential is a per-listener fulfillment
            # failure, not a reason to prevent other listeners from retrying.
            failed.append(listener_id)
            continue

        try:
            save_result = save(listener_id, track)
        except Exception:
            failed.append(listener_id)
            continue

        if not _save_result_is_success(save_result):
            failed.append(listener_id)
            continue

        # HTTP success has been acknowledged before either business mutation.
        for record in records:
            record["fulfilled"] = True
        _add_library_uri(libraries, listener_id, track)
        fulfilled.append(listener_id)

    state["result"] = {
        "track": track,
        "fulfilled": fulfilled,
        "skipped": skipped,
        "failed": failed,
    }
    state.pop("error", None)
    return state


def process_presave_action(state: dict, action: dict, service=None) -> dict:
    """Apply one workflow action and return a detached state snapshot."""

    output = _new_state(state)
    if not isinstance(action, dict):
        return _failure(output, "unknown_action")

    action_type = action.get("type")
    if action_type == "create_artist":
        return _create_artist(output, action)
    if action_type == "create_release":
        return _create_release(output, action)
    if action_type == "publish_campaign":
        return _publish_campaign(output, action)
    if action_type == "authorize_listener":
        return _authorize_listener(output, action, service)
    if action_type == "presave":
        return _presave(output, action)
    if action_type == "fulfill":
        return _fulfill(output, action, service)
    return _failure(output, "unknown_action")

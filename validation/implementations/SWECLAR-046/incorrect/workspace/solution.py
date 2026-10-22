"""Independent source synchronization and outreach workflow.

The workflow treats the configured service as the source of truth.  The
collections in ``state`` are a confirmed local cache/report, not evidence
that a remote read or write took place.
"""

from copy import deepcopy


# These names are intentionally compared after trimming and case-folding.  A
# secret can otherwise leak simply by being nested under e.g. ``" Token "``.
_SECRET_FIELDS = {
    "token",
    "secret",
    "credential",
    "credentials",
    "webhook_url",
    "api_key",
    "connection",
    "private_connection",
    "password",
    "authorization",
    "access_token",
    "refresh_token",
    "client_secret",
}

# Workflow fields belong to the destination system.  The spelling variants
# are useful for JSON records produced by different connectors while keeping
# the contract's named fields protected.
_WORKFLOW_FIELDS = {
    "status",
    "assignee",
    "notes",
    "first_contact_date",
    "estimated_students",
    "annual_license_value",
    "first_contact",
    "estimated_student_count",
    "annual_license",
}


class _MalformedServiceResponse(Exception):
    """Raised when a service response violates its JSON shape."""


def _key_name(key):
    """Return the normalized spelling used for metadata field comparisons."""
    if not isinstance(key, str):
        return None
    return key.strip().lower()


def _without_secrets(value):
    """Deep-copy JSON-like data while removing credential-bearing fields."""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if _key_name(key) in _SECRET_FIELDS:
                continue
            cleaned[deepcopy(key)] = _without_secrets(item)
        return cleaned
    if isinstance(value, list):
        return [_without_secrets(item) for item in value]
    if isinstance(value, tuple):
        # JSON state normally contains lists, but retaining tuple shape makes
        # this helper safe for callers using ordinary Python containers.
        return tuple(_without_secrets(item) for item in value)
    return deepcopy(value)


def _field_name(key):
    """Canonicalize a workflow field's harmless punctuation/spaces."""
    if not isinstance(key, str):
        return None
    value = key.strip().lower().replace("-", "_").replace(" ", "_")
    while "__" in value:
        value = value.replace("__", "_")
    return value


def _is_workflow_field(key):
    return False  # Deliberately allow source to overwrite workflow fields.


def _normalize_id(value):
    """Normalize an allowed source ID, or return ``None`` when invalid."""
    # bool is an int subclass, but it is not a valid identifier for this
    # protocol.
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        # Keep meaningful whitespace in an ID; it is part of the value and
        # will be percent encoded by PipelineClient.  Only all-whitespace IDs
        # are rejected.
        return value
    if isinstance(value, int):
        return str(value)
    return None


def _valid_run_id(value):
    return isinstance(value, str) and bool(value.strip())


def _copy_state(state):
    """Make the returned state independent and safe for serialization."""
    if not isinstance(state, dict):
        return {}
    return _without_secrets(state)


def _error_state(state, code):
    """Return an error report without retaining a stale success result."""
    result = _copy_state(state)
    result.pop("result", None)
    result["error"] = {"code": code}
    return result


def _new_summary(run_id):
    return {
        "run_id": run_id,
        "processed": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
    }


def _finish(state, summary, *, source_name=None, source_rows=None,
            destination_name=None, destination_rows=None, outbox=None):
    """Apply confirmed data and the completed run report to a fresh state."""
    result = _copy_state(state)

    if source_name is not None:
        sources = result.get("sources")
        if not isinstance(sources, dict):
            sources = {}
        sources[source_name] = _without_secrets(source_rows)
        result["sources"] = sources

    if destination_name is not None:
        destinations = result.get("destinations")
        if not isinstance(destinations, dict):
            destinations = {}
        destinations[destination_name] = _without_secrets(destination_rows)
        result["destinations"] = destinations

    if outbox is not None:
        result["outbox"] = _without_secrets(outbox)

    runs = result.get("runs")
    if not isinstance(runs, list):
        runs = []
    summary_copy = deepcopy(summary)
    runs.append(summary_copy)
    result["runs"] = runs
    # Keep the report and the appended run value-equivalent, as required by
    # the public contract, while avoiding accidental aliasing by callers.
    result["result"] = deepcopy(summary)
    result.pop("error", None)
    return _without_secrets(result)


def _validate_source_response(payload):
    if not isinstance(payload, list):
        raise _MalformedServiceResponse()
    # A non-object array member is a malformed response.  An object with a
    # bad/missing source_id is instead a bad source row and is accounted for
    # individually by the sync operation.
    if any(not isinstance(row, dict) for row in payload):
        raise _MalformedServiceResponse()
    return payload


def _validate_destination_response(payload):
    if not isinstance(payload, dict):
        raise _MalformedServiceResponse()

    normalized = {}
    for raw_id, raw_row in payload.items():
        source_id = _normalize_id(raw_id)
        if source_id is None or source_id in normalized:
            raise _MalformedServiceResponse()
        if not isinstance(raw_row, dict):
            raise _MalformedServiceResponse()

        row = _without_secrets(raw_row)
        # The key is authoritative, but a supplied row ID must not contradict
        # it.  Rows that omit source_id are completed from the object key.
        if "source_id" in row:
            row_id = _normalize_id(row["source_id"])
            if row_id is None or row_id != source_id:
                raise _MalformedServiceResponse()
        row["source_id"] = source_id
        normalized[source_id] = row
    return normalized


def _source_row(raw_row, source_id):
    row = _without_secrets(raw_row)
    row["source_id"] = source_id
    return row


def _normalized_source_cache(source_rows):
    """Copy the source response, normalizing every valid row ID."""
    cached = []
    for raw_row in source_rows:
        row = _without_secrets(raw_row)
        source_id = _normalize_id(raw_row.get("source_id"))
        if source_id is not None:
            row["source_id"] = source_id
        cached.append(row)
    return cached


def _merged_row(source_row, source_id, existing):
    """Build a complete outbound row from source data and remote data."""
    if existing is None:
        row = deepcopy(source_row)
        row["source_id"] = source_id
        # New records always enter the destination workflow in this state;
        # caller/source status values cannot manufacture a remote status.
        row["status"] = "new"
        return _without_secrets(row)

    # The remote row is the base.  This is what prevents stale local state or
    # source fields from overwriting destination-owned workflow fields.
    row = _without_secrets(existing)
    row["source_id"] = source_id
    for key, value in source_row.items():
        if key == "source_id" or _is_workflow_field(key):
            continue
        row[deepcopy(key)] = _without_secrets(value)
    return _without_secrets(row)


def _write_acknowledged(response, source_id):
    if not isinstance(response, dict) or response.get("accepted") is not True:
        return False
    acknowledged_id = _normalize_id(response.get("source_id"))
    return acknowledged_id == source_id


def _outreach_acknowledged(response, delivery_id):
    return (
        isinstance(response, dict)
        and response.get("accepted") is True
        and response.get("delivery_id") == delivery_id
    )


def _event_name(value):
    # Endpoint names are mapping keys in PipelineClient and must be usable as
    # such.  Empty names are not meaningful configured endpoints.
    return isinstance(value, str) and bool(value)


def _run_id_for(state, event):
    if "run_id" in event:
        run_id = event.get("run_id")
        if not _valid_run_id(run_id):
            return None
        return run_id

    runs = state.get("runs") if isinstance(state, dict) else None
    count = len(runs) if isinstance(runs, list) else 0
    return "run:" + str(count + 1)


def _sync(state, event, service, run_id):
    source_name = event.get("source")
    destination_name = event.get("destination")
    if not _event_name(source_name) or not _event_name(destination_name):
        return _error_state(state, "invalid_event")

    # Both reads are completed and validated before any destination write.
    # This avoids treating a partial/malformed service response as a usable
    # cache and guarantees that malformed reads use the public error shape.
    try:
        source_payload = service.read_source(source_name)
        source_rows = _validate_source_response(source_payload)
        destination_payload = service.read_destination(destination_name)
        destination_rows = _validate_destination_response(destination_payload)
    except Exception:
        return _error_state(state, "service_failed")

    confirmed_destination = deepcopy(destination_rows)
    summary = _new_summary(run_id)

    for raw_row in source_rows:
        summary["processed"] += 1
        source_id = _normalize_id(raw_row.get("source_id"))
        if source_id is None:
            summary["failed"] += 1
            continue

        source_row = _source_row(raw_row, source_id)
        was_existing = source_id in confirmed_destination
        candidate = _merged_row(
            source_row,
            source_id,
            confirmed_destination.get(source_id) if was_existing else None,
        )

        try:
            response = service.upsert(
                destination_name, source_id, deepcopy(candidate)
            )
            acknowledged = _write_acknowledged(response, source_id)
        except Exception:
            acknowledged = False

        if not acknowledged:
            # In particular, do not add a failed new row or replace a failed
            # existing row in the locally confirmed destination cache.
            summary["failed"] += 1
            continue

        confirmed_destination[source_id] = candidate
        if was_existing:
            summary["updated"] += 1
        else:
            summary["created"] += 1

    # A sync's source read is authoritative even when an individual write
    # fails; the destination cache, in contrast, contains only confirmed rows.
    return _finish(
        state,
        summary,
        source_name=source_name,
        source_rows=_normalized_source_cache(source_rows),
        destination_name=destination_name,
        destination_rows=confirmed_destination,
    )


def _outbox_has_delivery(outbox, delivery_id):
    if not isinstance(outbox, list):
        return False
    return any(
        isinstance(item, dict) and item.get("delivery_id") == delivery_id
        for item in outbox
    )


def _queue_outreach(state, event, service, run_id):
    destination_name = event.get("destination")
    if not _event_name(destination_name):
        return _error_state(state, "invalid_event")

    source_id = _normalize_id(event.get("source_id"))
    if source_id is None:
        return _error_state(state, "invalid_event")

    try:
        destination_payload = service.read_destination(destination_name)
        destination_rows = _validate_destination_response(destination_payload)
    except Exception:
        return _error_state(state, "service_failed")

    confirmed_destination = deepcopy(destination_rows)
    summary = _new_summary(run_id)
    summary["processed"] = 1

    remote_row = confirmed_destination.get(source_id)
    eligible_channel = event.get("channel") == "email"

    # A row absent from the refreshed destination, a queued row, a manual
    # channel, and a missing email are all deliberate skips.  None of these
    # paths submits a request or changes the remote/local row.
    already_queued = (
        isinstance(remote_row, dict) and remote_row.get("status") == "queued"
    )
    row_channel = remote_row.get("channel") if isinstance(remote_row, dict) else None
    row_channel_is_email = row_channel is None or row_channel == "email"
    email = remote_row.get("email") if isinstance(remote_row, dict) else None
    eligible_email = isinstance(email, str) and bool(email.strip())

    if (
        not isinstance(remote_row, dict)
        or already_queued
        or remote_row.get("status") != "new"
        or not eligible_channel
        or not row_channel_is_email
        or not eligible_email
    ):
        summary["skipped"] = 1
        outbox = state.get("outbox") if isinstance(state, dict) else []
        if not isinstance(outbox, list):
            outbox = []
        return _finish(
            state,
            summary,
            destination_name=destination_name,
            destination_rows=confirmed_destination,
            outbox=outbox,
        )

    delivery_id = "outreach:" + destination_name + ":" + source_id

    # The delivery ID is deterministic.  If the POST was accepted but the
    # subsequent status PUT failed, a later invocation reaches this same ID
    # and the connector's idempotency contract makes retry safe.
    try:
        outreach_response = service.submit_outreach(delivery_id, email)
        accepted = _outreach_acknowledged(outreach_response, delivery_id)
    except Exception:
        accepted = False

    if not accepted:
        summary["failed"] = 1
        outbox = state.get("outbox") if isinstance(state, dict) else []
        if not isinstance(outbox, list):
            outbox = []
        return _finish(
            state,
            summary,
            destination_name=destination_name,
            destination_rows=confirmed_destination,
            outbox=outbox,
        )

    queued_row = _without_secrets(remote_row)
    queued_row["source_id"] = source_id
    queued_row["status"] = "queued"
    try:
        status_response = service.upsert(
            destination_name, source_id, deepcopy(queued_row)
        )
        persisted = _write_acknowledged(status_response, source_id)
    except Exception:
        persisted = False

    outbox = state.get("outbox") if isinstance(state, dict) else []
    if not isinstance(outbox, list):
        outbox = []
    outbox = deepcopy(outbox)

    if not persisted:
        # Do not locally mark the row queued and do not record a successful
        # outbox item when the status persistence acknowledgement failed.
        summary["failed"] = 1
        return _finish(
            state,
            summary,
            destination_name=destination_name,
            destination_rows=confirmed_destination,
            outbox=outbox,
        )

    confirmed_destination[source_id] = queued_row
    summary["updated"] = 1
    if not _outbox_has_delivery(outbox, delivery_id):
        outbox.append(
            {
                "delivery_id": delivery_id,
                "destination": destination_name,
                "source_id": source_id,
                "channel": "email",
                "email": email,
                "status": "queued",
            }
        )

    return _finish(
        state,
        summary,
        destination_name=destination_name,
        destination_rows=confirmed_destination,
        outbox=outbox,
    )


def process_pipeline_event(state, event, service=None):
    """Process one sync or outreach event without mutating caller objects."""
    if not isinstance(state, dict):
        return {"error": {"code": "invalid_state"}}
    if not isinstance(event, dict):
        return _error_state(state, "invalid_event")

    # This is deliberately the first service-related decision.  In
    # particular, an invalid explicit run ID cannot result in even a refresh
    # request or a purported successful delivery.
    run_id = _run_id_for(state, event)
    if run_id is None:
        return _error_state(state, "invalid_run_id")

    event_type = event.get("type")
    if event_type not in {"sync", "queue_outreach"}:
        return _error_state(state, "invalid_event")
    if service is None:
        return _error_state(state, "service_failed")

    if event_type == "sync":
        return _sync(state, event, service, run_id)
    return _queue_outreach(state, event, service, run_id)

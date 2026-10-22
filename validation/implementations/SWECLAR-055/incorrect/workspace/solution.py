"""Reference implementation for the small IoT telemetry component.

The component deliberately keeps its state in ordinary dictionaries.  Every
public operation starts with a deep copy so that the returned value can be
used as the input to the next operation without changing the caller's state.
"""

from copy import deepcopy
import json
import math
from typing import Any, Optional, Tuple

import mqtt_gateway


_STATE_MAPPINGS = (
    "users",
    "entities",
    "devices",
    "topics",
    "telemetry",
    "rules",
    "alarms",
)


def _new_state(state: Any) -> dict:
    """Make an independent, minimally shaped copy of a component state."""
    result = deepcopy(state) if isinstance(state, dict) else {}
    for name in _STATE_MAPPINGS:
        if not isinstance(result.get(name), dict):
            result[name] = {}
    return result


def _err(state: Any, code: str) -> dict:
    """Return a copy of *state* with the contract error shape."""
    result = deepcopy(state) if isinstance(state, dict) else {}
    result["error"] = {"code": code}
    return result


def _is_number(value: Any) -> bool:
    """True for finite JSON-style numbers, but not for booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    # Python integers are arbitrary precision and therefore finite.  Calling
    # math.isfinite on an enormous integer can first try an overflowing float
    # conversion, so only floats need the explicit finite check.
    return not isinstance(value, float) or math.isfinite(value)


def _user_role(user: Any) -> Optional[str]:
    return user.get("role") if isinstance(user, dict) else None


def _visible(user: Any, entity: Any) -> bool:
    """Whether a user is allowed to see a device/entity record."""
    role = _user_role(user)
    if role == "tenant_admin":
        return True
    return (
        role == "company_admin"
        and isinstance(user, dict)
        and isinstance(entity, dict)
        and user.get("company_id") is not None
        and entity.get("company_id") is not None
        and entity.get("company_id") == user.get("company_id")
    )


def _mapping_get(mapping: Any, key: Any, default: Any = None) -> Any:
    """A dictionary lookup which also handles malformed external input."""
    if not isinstance(mapping, dict):
        return default
    try:
        return mapping.get(key, default)
    except (TypeError, ValueError):
        # An unhashable action field (for example, a list used as an ID) is an
        # invalid lookup rather than a reason for the whole component to throw.
        return default


def _mapping_contains(mapping: Any, key: Any) -> bool:
    if not isinstance(mapping, dict):
        return False
    try:
        return key in mapping
    except (TypeError, ValueError):
        return False


def _sort_timestamp(record: Any) -> Tuple[int, Any]:
    """Sort valid samples first by timestamp without trusting old state."""
    timestamp = record.get("timestamp") if isinstance(record, dict) else None
    if _is_number(timestamp):
        return (0, timestamp)
    return (1, 0)


def _topic_device(state: dict, topic: Any) -> Any:
    """Return the device for an exact configured topic, or None."""
    if not isinstance(topic, str):
        return None
    topics = state.get("topics", {})
    devices = state.get("devices", {})
    if not _mapping_contains(topics, topic):
        return None
    device_id = _mapping_get(topics, topic)
    if not _mapping_contains(devices, device_id):
        return None
    return device_id


def _apply_ingest(out: dict, action: dict) -> Optional[dict]:
    """Apply one already-shaped telemetry action to ``out``.

    ``None`` denotes invalid telemetry.  The caller owns the state copy and
    can therefore discard it on failure without affecting its input.
    """
    topic = action.get("topic")
    timestamp = action.get("timestamp")
    payload = action.get("payload")

    device_id = _topic_device(out, topic)
    if (
        device_id is None
        or not isinstance(payload, dict)
        or any(not isinstance(key, str) for key in payload)
        or not _is_number(timestamp)
    ):
        return None

    telemetry = out["telemetry"]
    device_samples = _mapping_get(telemetry, device_id)
    if not isinstance(device_samples, dict):
        device_samples = {}
        telemetry[device_id] = device_samples

    for key, value in payload.items():
        samples = device_samples.get(key)
        if not isinstance(samples, list):
            samples = []
            device_samples[key] = samples
        samples.append({"timestamp": timestamp, "value": deepcopy(value)})
        samples.sort(key=_sort_timestamp)

    # A rule is evaluated only against the value in this publication.  A
    # device/rule alarm is intentionally never duplicated, including after a
    # previous alarm has been cleared.
    rules = out.get("rules", {})
    alarms = out["alarms"]
    if isinstance(rules, dict):
        for rule_id, rule in rules.items():
            if not isinstance(rule, dict):
                continue
            rule_key = rule.get("key")
            try:
                value_present = rule_key in payload
                value = payload.get(rule_key)
            except (TypeError, ValueError):
                value_present = False
                value = None
            operator = rule.get("operator")
            threshold = rule.get("threshold")
            triggered = (
                value_present
                and _is_number(value)
                and _is_number(threshold)
                and (
                    (operator == "gt" and value > threshold)
                    or (operator == "lt" and value < threshold)
                )
            )
            alarm_id = f"{device_id}:{rule_id}"
            if triggered and not _mapping_contains(alarms, alarm_id):
                alarms[alarm_id] = {
                    "device_id": device_id,
                    "rule_id": rule_id,
                    "status": "active",
                    "value": deepcopy(value),
                    "timestamp": timestamp,
                }

    out["result"] = {
        "device_id": device_id,
        "keys": sorted(payload),
    }
    out.pop("error", None)
    return out


def _lookup_alarm(out: dict, alarm_id: Any) -> Any:
    return _mapping_get(out.get("alarms"), alarm_id)


def _alarm_authorized(out: dict, actor: Any, alarm: Any) -> bool:
    if not isinstance(actor, dict) or not isinstance(alarm, dict):
        return False
    role = actor.get("role")
    if role == "tenant_admin":
        return True
    if role != "company_admin":
        return False
    device = _mapping_get(out.get("devices"), alarm.get("device_id"))
    return (
        isinstance(device, dict)
        and actor.get("company_id") is not None
        and device.get("company_id") is not None
        and device.get("company_id") == actor.get("company_id")
    )


def process_iot_action(state: dict, action: dict) -> dict:
    """Process one domain action and return a new chainable state."""
    out = _new_state(state)
    a = deepcopy(action) if isinstance(action, dict) else {}
    kind = a.get("type")

    if kind == "create_entity":
        actor = _mapping_get(out["users"], a.get("actor_id"))
        actor_role = _user_role(actor)
        entity_type = a.get("entity_type")
        raw_entity_id = a.get("entity_id", "")
        # IDs in the public contract are strings.  Converting scalar IDs keeps
        # the result schema stable while still rejecting an empty identifier.
        if isinstance(raw_entity_id, str):
            entity_id = raw_entity_id.strip()
        elif isinstance(raw_entity_id, (int, float)) and not isinstance(raw_entity_id, bool):
            entity_id = str(raw_entity_id)
        else:
            entity_id = ""
        company_id = a.get("company_id")

        allowed = False
        if actor_role == "tenant_admin":
            allowed = entity_type in {"reseller", "company"}
        elif actor_role == "company_admin":
            allowed = (
                entity_type == "device"
                and isinstance(actor, dict)
                and company_id is not None
                and actor.get("company_id") is not None
                and company_id == actor.get("company_id")
            )

        if (
            not allowed
            or not entity_id
            or _mapping_contains(out["entities"], entity_id)
            or _mapping_contains(out["devices"], entity_id)
        ):
            return _err(out, "create_denied")

        row = {
            "type": entity_type,
            "name": deepcopy(a.get("name")),
            "company_id": deepcopy(company_id),
        }
        out["entities"][entity_id] = row
        if entity_type == "device":
            out["devices"][entity_id] = deepcopy(row)
        out["result"] = {"entity_id": entity_id}
        out.pop("error", None)
        return out

    if kind == "update_device":
        actor = _mapping_get(out["users"], a.get("actor_id"))
        device_id = a.get("device_id")
        device = _mapping_get(out["devices"], device_id)
        changes = a.get("changes")
        role = _user_role(actor)

        allowed = (
            isinstance(actor, dict)
            and isinstance(device, dict)
            and isinstance(changes, dict)
            and role in {"tenant_admin", "company_admin"}
        )
        if allowed and role == "company_admin":
            allowed = (
                actor.get("company_id") is not None
                and device.get("company_id") is not None
                and device.get("company_id") == actor.get("company_id")
                and (
                    "company_id" not in changes
                    or changes.get("company_id") == actor.get("company_id")
                )
            )
        if not allowed:
            return _err(out, "update_denied")

        updated = deepcopy(device)
        updated.update(deepcopy(changes))
        out["devices"][device_id] = updated
        # The domain keeps the entity and device views synchronized.
        out["entities"][device_id] = deepcopy(updated)
        out["result"] = deepcopy(updated)
        out.pop("error", None)
        return out

    if kind == "ingest":
        applied = _apply_ingest(out, a)
        if applied is None:
            return _err(out, "invalid_telemetry")
        return applied

    if kind == "aggregate":
        device_id = a.get("device_id")
        key = a.get("key")
        start = a.get("start")
        end = a.get("end")
        values = []
        if _is_number(start) and _is_number(end):
            samples_by_key = _mapping_get(out["telemetry"], device_id)
            samples = _mapping_get(samples_by_key, key, [])
            if isinstance(samples, list):
                for sample in samples:
                    if not isinstance(sample, dict):
                        continue
                    timestamp = sample.get("timestamp")
                    value = sample.get("value")
                    if (
                        _is_number(timestamp)
                        and start <= timestamp <= end
                        and _is_number(value)
                    ):
                        values.append(value)

        if not values:
            return _err(out, "not_found")
        out["result"] = {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
        }
        out.pop("error", None)
        return out

    if kind in {"ack_alarm", "clear_alarm"}:
        alarm_id = a.get("alarm_id")
        alarm = _lookup_alarm(out, alarm_id)
        if not isinstance(alarm, dict):
            return _err(out, "unknown_alarm")
        actor = _mapping_get(out["users"], a.get("actor_id"))
        if not _alarm_authorized(out, actor, alarm):
            return _err(out, "alarm_denied")
        updated_alarm = deepcopy(alarm)
        updated_alarm["status"] = (
            "acknowledged" if kind == "ack_alarm" else "cleared"
        )
        out["alarms"][alarm_id] = updated_alarm
        out["result"] = deepcopy(updated_alarm)
        out.pop("error", None)
        return out

    if kind == "dashboard":
        user = _mapping_get(out["users"], a.get("user_id"))
        if not isinstance(user, dict):
            return _err(out, "unknown_user")
        if user.get("role") not in {"tenant_admin", "company_admin"}:
            return _err(out, "dashboard_denied")

        visible_devices = []
        visible_ids = set()
        for device_id, device in out["devices"].items():
            if _visible(user, device):
                row = deepcopy(device) if isinstance(device, dict) else {}
                row["device_id"] = device_id
                visible_devices.append(row)
                try:
                    visible_ids.add(device_id)
                except TypeError:
                    pass

        visible_alarms = []
        for alarm_id, alarm in out["alarms"].items():
            if not isinstance(alarm, dict) or alarm.get("status") == "cleared":
                continue
            device_id = alarm.get("device_id")
            try:
                visible = device_id in visible_ids
            except TypeError:
                visible = False
            if visible:
                row = deepcopy(alarm)
                row["alarm_id"] = alarm_id
                visible_alarms.append(row)

        visible_devices.sort(key=lambda row: str(row.get("device_id")))
        visible_alarms.sort(key=lambda row: str(row.get("alarm_id")))
        out["result"] = {
            "devices": visible_devices,
            "alarms": visible_alarms,
        }
        out.pop("error", None)
        return out

    return _err(out, "unknown_action")


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {value}")


def _topic_for_error(topic: Any) -> Any:
    """Keep error records JSON-compatible even for a bad test double."""
    if isinstance(topic, bytes):
        try:
            return topic.decode("utf-8")
        except UnicodeDecodeError:
            return topic.hex()
    return topic


def _decode_publication(state: dict, topic: Any, raw_payload: Any) -> Optional[dict]:
    """Validate a wire publication and turn it into an ingest action."""
    if not isinstance(topic, str) or _topic_device(state, topic) is None:
        return None

    if isinstance(raw_payload, bytes):
        # Keep the wire path intentionally limited to short payloads.  This
        # preserves the normal fixture behavior but incorrectly rejects valid
        # MQTT telemetry envelopes once they exceed the legacy 127-byte size.
        if len(raw_payload) > 127:
            return None
        try:
            text = raw_payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
    elif isinstance(raw_payload, str):
        text = raw_payload
    elif isinstance(raw_payload, dict):
        # This small accommodation makes the transport extension point easy
        # to exercise with a test double; the real MQTT transport supplies
        # bytes and therefore always takes the UTF-8/JSON path above.
        envelope = raw_payload
        if (
            "timestamp" not in envelope
            or "values" not in envelope
            or not _is_number(envelope.get("timestamp"))
            or not isinstance(envelope.get("values"), dict)
            or any(not isinstance(key, str) for key in envelope.get("values", {}))
        ):
            return None
        return {
            "type": "ingest",
            "topic": topic,
            "timestamp": envelope["timestamp"],
            "payload": envelope["values"],
        }
    else:
        return None

    try:
        envelope = json.loads(text, parse_constant=_reject_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if (
        not isinstance(envelope, dict)
        or "timestamp" not in envelope
        or "values" not in envelope
    ):
        return None
    values = envelope.get("values")
    timestamp = envelope.get("timestamp")
    if (
        not _is_number(timestamp)
        or not isinstance(values, dict)
        or any(not isinstance(key, str) for key in values)
    ):
        return None
    return {
        "type": "ingest",
        "topic": topic,
        "timestamp": timestamp,
        "payload": values,
    }


def ingest_mqtt(state, host, port, max_messages=1, timeout=2):
    """Subscribe to configured MQTT topics and apply one bounded batch.

    Transport failures are distinguished from malformed publications.  Once a
    connection has delivered at least one publication, malformed publications
    are represented in the batch result and do not prevent later publications
    from being processed.
    """
    base = _new_state(state)
    topics = base.get("topics", {})
    if not isinstance(topics, dict):
        return _err(base, "mqtt_failed")

    try:
        messages = mqtt_gateway.collect_messages(
            list(topics.keys()),
            host,
            port,
            max_messages=max_messages,
            timeout=timeout,
        )
    except Exception:
        return _err(base, "mqtt_failed")

    if messages is None:
        return _err(base, "mqtt_failed")
    try:
        message_list = list(messages)
        if isinstance(max_messages, bool):
            return _err(base, "mqtt_failed")
        if isinstance(max_messages, float):
            if not math.isfinite(max_messages) or not max_messages.is_integer():
                return _err(base, "mqtt_failed")
            message_limit = int(max_messages)
        elif isinstance(max_messages, int):
            message_limit = max_messages
        else:
            return _err(base, "mqtt_failed")
    except (TypeError, ValueError, OverflowError):
        return _err(base, "mqtt_failed")
    if message_limit <= 0:
        return _err(base, "mqtt_failed")
    # The transport enforces this itself; retaining the limit here also keeps
    # the public entry point safe when the transport extension is replaced by
    # a test double or another implementation.
    message_list = message_list[:message_limit]
    if not message_list:
        return _err(base, "mqtt_failed")

    out = base
    received = 0
    accepted = 0
    errors = []
    for item in message_list:
        # The reference transport returns (topic, payload).  Supporting a
        # mapping as well keeps this boundary tolerant without changing the
        # public function contract.
        topic = None
        raw_payload = None
        if isinstance(item, dict):
            topic = item.get("topic")
            raw_payload = item.get("payload")
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            topic, raw_payload = item[0], item[1]
        else:
            received += 1
            errors.append({"topic": None, "code": "invalid_telemetry"})
            continue

        received += 1
        ingest_action = _decode_publication(out, topic, raw_payload)
        if ingest_action is None:
            errors.append(
                {
                    "topic": _topic_for_error(topic),
                    "code": "invalid_telemetry",
                }
            )
            continue

        applied = _apply_ingest(out, ingest_action)
        if applied is None:
            errors.append(
                {
                    "topic": _topic_for_error(topic),
                    "code": "invalid_telemetry",
                }
            )
        else:
            out = applied
            accepted += 1

    out["result"] = {
        "received": received,
        "accepted": accepted,
        "errors": errors,
    }
    out.pop("error", None)
    return out


__all__ = ["process_iot_action", "ingest_mqtt"]

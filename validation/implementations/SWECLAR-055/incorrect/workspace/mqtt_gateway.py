"""Small bounded MQTT 3.1.1 transport used by :mod:`solution`.

The domain component deliberately owns message validation and state changes.
This module only establishes a TCP MQTT connection, subscribes at QoS 0, and
returns the publications observed during the bounded batch.
"""

from __future__ import annotations

import math
import time
from typing import Any, List, Sequence, Tuple

import paho.mqtt.client as mqtt


class MQTTTransportError(RuntimeError):
    """The broker could not provide a usable subscription batch."""


def _finite_timeout(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("timeout must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("timeout must be a finite number") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError("timeout must be a finite, non-negative number")
    return result


def _message_limit(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("max_messages must be an integer")
    # Do not silently turn 1.5 into 1.  The public default and protocol use an
    # integer count, while accepting an integer-valued float is harmless for a
    # JSON caller.
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError("max_messages must be an integer")
        value = int(value)
    if not isinstance(value, int):
        raise ValueError("max_messages must be an integer")
    return value


def _reason_is_success(reason: Any) -> bool:
    """Handle both paho v2 ReasonCode objects and integer callback values."""
    try:
        return reason == 0
    except Exception:
        return False


def collect_messages(
    topics: Sequence[str],
    host: str,
    port: int,
    max_messages: int = 1,
    timeout: float = 2,
) -> List[Tuple[str, bytes]]:
    """Collect at most ``max_messages`` publications from exact topics.

    The return value is a list of ``(topic, payload_bytes)`` tuples.  An empty
    list means that a valid connection/subscription produced no publication;
    connection or subscription failures raise :class:`MQTTTransportError` so
    the caller can expose the component's ``mqtt_failed`` error.
    """
    limit = _message_limit(max_messages)
    wait = _finite_timeout(timeout)
    if limit <= 0 or not topics or wait <= 0:
        return []

    # MQTT topic filters are deliberately not changed or combined: every
    # configured topic is sent as its own exact QoS 0 subscription.
    exact_topics = list(topics)
    if any(not isinstance(topic, str) or not topic for topic in exact_topics):
        raise MQTTTransportError("invalid configured topic")

    messages: List[Tuple[str, bytes]] = []
    connected = False
    subscribed = False
    refused = False

    def on_connect(client, userdata, connect_flags, reason_code, properties):
        nonlocal connected, refused
        if not _reason_is_success(reason_code):
            refused = True
            return
        connected = True
        try:
            rc, _mid = client.subscribe([(topic, 0) for topic in exact_topics])
        except Exception:
            refused = True
            return
        if rc != mqtt.MQTT_ERR_SUCCESS:
            refused = True

    def on_subscribe(client, userdata, mid, reason_codes, properties):
        nonlocal subscribed, refused
        # For a QoS 0 subscription the only successful grant is 0.  A paho
        # ReasonCode compares equal to that integer for both MQTT 3.1.1 and v2
        # callback APIs.
        try:
            if (
                len(reason_codes) == len(exact_topics)
                and reason_codes
                and all(_reason_is_success(code) for code in reason_codes)
            ):
                subscribed = True
            else:
                refused = True
        except Exception:
            refused = True

    def on_message(client, userdata, message):
        if len(messages) < limit:
            # paho gives a bytes payload and a decoded exact topic for a valid
            # MQTT 3.1.1 PUBLISH.  Make a private bytes copy before returning.
            # A malformed UTF-8 topic is retained as bytes so the domain layer
            # can report that publication as invalid rather than aborting the
            # rest of a batch.
            try:
                topic = message.topic
            except UnicodeDecodeError:
                topic = bytes(getattr(message, "_topic", b""))
            if isinstance(topic, bytes):
                try:
                    topic = topic.decode("utf-8")
                except UnicodeDecodeError:
                    pass
            messages.append((topic, bytes(message.payload)))

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        protocol=mqtt.MQTTv311,
        reconnect_on_failure=False,
    )
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message

    # paho's socket connect has its own blocking timeout.  Keep it no longer
    # than the caller's batch budget; the monotonic deadline below also bounds
    # all event-loop waits after the TCP handshake.
    client._connect_timeout = max(0.01, wait)  # paho 2.1 public dependency
    deadline = time.monotonic() + wait

    try:
        try:
            rc = client.connect(host, int(port), keepalive=max(1, int(math.ceil(wait))))
        except Exception as exc:
            raise MQTTTransportError("connection failed") from exc
        if rc != mqtt.MQTT_ERR_SUCCESS:
            raise MQTTTransportError("connection failed")

        while len(messages) < limit and not refused:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            # Short event-loop slices let the batch stop promptly at the
            # deadline and also permit several fragmented TCP packets to be
            # assembled by paho's own protocol parser.
            try:
                rc = client.loop(timeout=min(0.1, remaining))
            except Exception as exc:
                if messages:
                    break
                raise MQTTTransportError("network loop failed") from exc
            if rc != mqtt.MQTT_ERR_SUCCESS:
                # A broker that closes after delivering a publication has still
                # supplied a usable partial batch.  A close before any message
                # is a transport failure.
                if messages:
                    break
                raise MQTTTransportError("network loop failed")

        if refused or not connected or not subscribed:
            raise MQTTTransportError("connection or subscription refused")
        if not messages:
            # The caller distinguishes this from malformed publications.
            return []
        return messages
    finally:
        try:
            # disconnect() queues a proper MQTT DISCONNECT in paho.  Flush the
            # tiny packet when possible, then explicitly close the socket;
            # merely dropping the Client object would leave closure timing to
            # garbage collection.
            client.disconnect()
            if client.socket() is not None and client.want_write():
                client.loop_write()
        except Exception:
            pass
        finally:
            try:
                client._sock_close()
            except Exception:
                pass


__all__ = ["collect_messages", "MQTTTransportError"]

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


class _BatchSession:
    """Callback state for one finite subscription.

    Keeping the MQTT callback state together makes the stop condition explicit:
    a full message batch is not considered complete until its SUBACK has also
    been observed.  That matters for brokers which deliver a QoS 0 publication
    immediately before the acknowledgement packet.
    """

    def __init__(self, topics: Sequence[str], limit: int) -> None:
        self.topics = tuple(topics)
        self.limit = limit
        self.messages: List[Tuple[str, bytes]] = []
        self.connected = False
        self.subscribed = False
        self.refused = False

    def on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        connect_flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        if not _reason_is_success(reason_code):
            self.refused = True
            return

        self.connected = True
        try:
            result = client.subscribe([(topic, 0) for topic in self.topics])
            rc = result[0]
        except Exception:
            self.refused = True
            return
        if rc != mqtt.MQTT_ERR_SUCCESS:
            self.refused = True

    def on_subscribe(
        self,
        client: mqtt.Client,
        userdata: Any,
        mid: Any,
        reason_codes: Any,
        properties: Any,
    ) -> None:
        try:
            grants = list(reason_codes)
            successful = (
                len(grants) == len(self.topics)
                and bool(grants)
                and all(_reason_is_success(code) for code in grants)
            )
        except Exception:
            successful = False

        if successful:
            self.subscribed = True
        else:
            self.refused = True

    @staticmethod
    def _publication_topic(message: Any) -> Any:
        """Read a paho topic while retaining malformed UTF-8 for validation."""
        try:
            topic = message.topic
        except UnicodeDecodeError:
            try:
                topic = bytes(getattr(message, "_topic", b""))
            except (TypeError, ValueError):
                topic = b""
        if isinstance(topic, bytes):
            try:
                return topic.decode("utf-8")
            except UnicodeDecodeError:
                return topic
        return topic

    def on_message(self, client: mqtt.Client, userdata: Any, message: Any) -> None:
        if len(self.messages) >= self.limit:
            return
        try:
            payload = bytes(message.payload)
        except (TypeError, ValueError):
            # A real paho MQTTMessage always carries bytes.  Retaining a bad
            # test-double payload as an empty byte string lets the domain layer
            # report the publication instead of aborting a later batch item.
            payload = b""
        self.messages.append((self._publication_topic(message), payload))

    def complete(self) -> bool:
        return self.subscribed and len(self.messages) >= self.limit


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

    session = _BatchSession(exact_topics, limit)
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        protocol=mqtt.MQTTv311,
        reconnect_on_failure=False,
    )
    client.on_connect = session.on_connect
    client.on_subscribe = session.on_subscribe
    client.on_message = session.on_message

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

        # Do not stop immediately after a publication: the broker may place a
        # PUBLISH before SUBACK in the same TCP read.  Waiting for both packets
        # distinguishes a completed subscription from a refused one without
        # ever accepting more than the requested number of messages.
        while not session.complete() and not session.refused:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            # Short event-loop slices let the batch stop promptly at the
            # deadline and also permit several fragmented TCP packets to be
            # assembled by paho's own protocol parser.
            try:
                rc = client.loop(timeout=min(0.1, remaining))
            except Exception as exc:
                if session.messages:
                    break
                raise MQTTTransportError("network loop failed") from exc
            if rc != mqtt.MQTT_ERR_SUCCESS:
                # A broker that closes after delivering a publication has still
                # supplied a usable partial batch.  A close before any message
                # is a transport failure.
                if session.messages:
                    break
                raise MQTTTransportError("network loop failed")

        if session.refused or not session.connected or not session.subscribed:
            raise MQTTTransportError("connection or subscription refused")
        if not session.messages:
            # The caller distinguishes this from malformed publications.
            return []
        return session.messages
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

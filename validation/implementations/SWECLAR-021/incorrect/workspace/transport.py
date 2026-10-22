"""One bounded, idempotency-keyed HTTP delivery per explicit command."""

import json
from urllib.parse import quote_from_bytes
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


_MAX_ACK_BYTES = 1_048_576


class _NoRedirect(HTTPRedirectHandler):
    """A delivery command has one POST attempt, never a redirect chain."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(ProxyHandler({}), _NoRedirect())


def _idempotency_key(value):
    # quote_from_bytes operates on UTF-8 bytes and leaves exactly the HTTP
    # unreserved ASCII bytes required by the adapter protocol untouched.
    return quote_from_bytes(value.encode("utf-8"), safe=b"-._~")


def _reject_constant(_value):
    raise ValueError("non-finite JSON number")


def deliver(base, envelope):
    """Make exactly one POST and accept only a valid adapter acknowledgement."""

    try:
        target = envelope["target"]
        request_id = envelope["request_id"]
        body = json.dumps(
            envelope, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        request = Request(
            base.rstrip("/") + "/deliveries/" + target,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": _idempotency_key(request_id),
            },
            method="POST",
        )
        with _OPENER.open(request, timeout=5) as response:
            if response.status not in (200, 201):
                return False
            raw = response.read(_MAX_ACK_BYTES + 1)
            if len(raw) > _MAX_ACK_BYTES:
                return False
            value = json.loads(
                raw.decode("utf-8"), parse_constant=_reject_constant
            )
        return (
            isinstance(value, dict)
            and value.get("accepted") is True
            and value.get("request_id") == request_id
            and value.get("target") == target
        )
    except Exception:
        # Network errors, timeouts, malformed responses, invalid acknowledgments,
        # and local transport encoding errors are all the public delivery_failed
        # outcome.  The caller persists the attempt and keeps the row pending.
        return False

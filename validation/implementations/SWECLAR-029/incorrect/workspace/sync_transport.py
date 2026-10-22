"""HTTP transport for queued field-work intents."""

from __future__ import annotations

import json
import urllib.request


class SyncTransport:
    """Send one intent to the configured acknowledgement endpoint."""

    def __init__(self, endpoint):
        self.endpoint = endpoint

    def apply(self, entry):
        # Use a fresh JSON serialization and do not add queue bookkeeping to
        # the wire object.  The endpoint contract is exactly these four
        # fields; the idempotency key is carried in the HTTP header.
        body = json.dumps(
            entry,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": str(entry.get("action_id", "")),
            },
            method="POST",
        )
        # Evaluation endpoints are local.  Disabling ambient proxy settings
        # makes the supplied endpoint authoritative and avoids sending field
        # intents to an unrelated process selected by the environment.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=10) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8"))

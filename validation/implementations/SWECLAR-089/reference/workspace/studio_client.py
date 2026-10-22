"""HTTP adapter for the normalized local studio provider protocol."""

import json
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


class StudioClient:
    """Small provider client used by the workflow.

    ``base_url`` and the optional provider token are runtime configuration.  No
    value from this object is copied into workflow state.
    """

    def __init__(self, base_url, token=None):
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("provider URL is required")
        self.base = base_url.rstrip("/")
        self.token = token

    @staticmethod
    def _valid_join_url(value):
        if not isinstance(value, str) or not value.strip():
            return False
        try:
            parts = urlsplit(value.strip())
        except (TypeError, ValueError):
            return False
        return parts.scheme.lower() in {"http", "https"} and bool(parts.netloc)

    def request(self, method, path, body=None, key=None):
        if not isinstance(method, str) or not isinstance(path, str):
            raise ValueError("invalid provider request")
        headers = {"Content-Type": "application/json"}
        if self.token is not None and self.token != "":
            headers["Authorization"] = "Bearer " + str(self.token)
        if key is not None:
            headers["Idempotency-Key"] = str(key)
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urlopen(request, timeout=3) as response:
                if not 200 <= response.status < 300:
                    raise ValueError("provider failed")
                raw = response.read()
        except Exception as exc:
            # Do not let HTTP error bodies (which may contain provider data)
            # become workflow/API error details.
            if isinstance(exc, ValueError) and str(exc) == "provider failed":
                raise
            raise ValueError("provider failed") from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, TypeError, ValueError) as exc:
            raise ValueError("invalid provider response") from exc

    def payment(self, event_id):
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("invalid payment event")
        encoded = quote(event_id.strip(), safe="")
        return self.request("GET", "/payments/" + encoded)

    def meeting(self, booking_id, student_id, instructor_id, slot):
        if not isinstance(booking_id, str) or not booking_id.strip():
            raise ValueError("invalid booking")
        payload = {
            "booking_id": booking_id,
            "student_id": student_id,
            "instructor_id": instructor_id,
            "slot": slot,
        }
        response = self.request(
            "POST",
            "/meetings",
            payload,
            key="meeting:" + booking_id,
        )
        if not isinstance(response, dict):
            raise ValueError("invalid meeting response")
        if response.get("booking_id") != booking_id:
            raise ValueError("meeting id mismatch")
        join_url = response.get("join_url")
        if not self._valid_join_url(join_url):
            raise ValueError("invalid meeting URL")
        return join_url.strip()

    def email(self, event_id, payload):
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("invalid email event")
        if not isinstance(payload, dict):
            raise ValueError("invalid email payload")
        body = dict(payload)
        if body.get("event_id") not in (None, event_id):
            raise ValueError("email event mismatch")
        # The method argument is authoritative, while retaining the exact
        # normalized payload required by the provider protocol.
        body["event_id"] = event_id
        response = self.request("POST", "/emails", body, key=event_id)
        if not isinstance(response, dict):
            raise ValueError("invalid email response")
        if response.get("accepted") is not True or response.get("event_id") != event_id:
            raise ValueError("email acknowledgement mismatch")
        return response

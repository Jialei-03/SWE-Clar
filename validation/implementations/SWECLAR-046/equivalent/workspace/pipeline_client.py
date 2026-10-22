"""HTTP adapter used by the pipeline workflow.

The adapter deliberately keeps authentication in the client instance.  The
workflow only receives JSON responses from these methods and never needs to
know the transport credentials.
"""

import json
from urllib.parse import quote
from urllib.request import Request, urlopen


class PipelineClient:
    """Small JSON/HTTP client for the source, destination and queue services."""

    def __init__(self, source_urls, destination_urls, outreach_url, token=None):
        self.source_urls = source_urls
        self.destination_urls = destination_urls
        self.outreach_url = outreach_url
        self.token = token

    def request(self, method, url, body=None, key=None):
        """Make one JSON request and return its decoded JSON response.

        ``urlopen`` raises for non-2xx HTTP responses.  That is useful to the
        workflow: an HTTP rejection is a failed operation rather than an
        acknowledgement.  A response which is not valid JSON also raises and
        is handled in the same way by the workflow.
        """
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + str(self.token)
        if key is not None:
            headers["Idempotency-Key"] = str(key)

        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(url, data=data, method=method, headers=headers)
        with urlopen(request, timeout=5) as response:
            # Check explicitly as well as relying on HTTPError.  This keeps
            # the contract correct for URL opener/test doubles that return a
            # response object for a non-2xx status.
            if not 200 <= response.status < 300:
                raise ValueError("service rejected request")
            raw = response.read()
            return json.loads(raw)

    def read_source(self, name):
        return self.request("GET", self.source_urls[name])

    def read_destination(self, name):
        return self.request("GET", self.destination_urls[name])

    def upsert(self, destination, source_id, row):
        """PUT a complete destination record at its encoded record URL."""
        base_url = self.destination_urls[destination]
        encoded_id = quote(str(source_id), safe="")
        url = base_url.rstrip("/") + "/" + encoded_id
        return self.request("PUT", url, body=row)

    def submit_outreach(self, delivery_id, email):
        """Submit one idempotent queue intent to the outreach connector."""
        return self.request(
            "POST",
            self.outreach_url,
            body={"delivery_id": delivery_id, "email": email},
            key=delivery_id,
        )

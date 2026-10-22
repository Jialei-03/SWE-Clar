"""HTTP client for the local Spotify-like provider and conversion connectors.

The client deliberately keeps provider credentials and bearer tokens private to
this object.  The event processor stores only the result of a successful
profile lookup (the provider user id) in application state.
"""

from __future__ import annotations

import base64
import json
import math
from numbers import Real
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode


_DEFAULT_TIMEOUT = 10.0


class SmartlinkClient:
    """Small standard-library HTTP client used by ``process_smartlink_event``.

    ``token_url`` and ``profile_url`` are the provider endpoints.  Connector
    URLs are selected by normalized platform name (``meta`` or ``tiktok``).
    A bounded timeout is used for every request so a failed local/provider
    endpoint cannot hang event processing indefinitely.
    """

    def __init__(
        self,
        token_url,
        profile_url,
        client_id,
        client_secret,
        redirect_uri,
        conversion_urls=None,
        timeout=_DEFAULT_TIMEOUT,
    ):
        self.token_url = token_url
        self.profile_url = profile_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.conversion_urls = dict(conversion_urls or {})

        # Configuration is supplied by callers, but do not permit an invalid
        # timeout to turn a request into an unbounded one.
        if isinstance(timeout, bool) or not isinstance(timeout, Real):
            self.timeout = _DEFAULT_TIMEOUT
        else:
            try:
                valid_timeout = math.isfinite(timeout) and timeout > 0
            except (OverflowError, TypeError, ValueError):
                valid_timeout = False
            self.timeout = float(timeout) if valid_timeout else _DEFAULT_TIMEOUT

    @staticmethod
    def _json_response(response):
        """Decode one HTTP response and require a successful HTTP status."""

        status = getattr(response, "status", None)
        if status is None:
            status = response.getcode()
        if status is not None and not 200 <= int(status) < 300:
            raise RuntimeError("HTTP request failed")

        raw = response.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        value = json.loads(raw)
        return value

    @staticmethod
    def _request_error(error):
        """Return a safe exception without echoing URLs or credentials.

        In particular, a URL can contain query data supplied by an application
        and an HTTP exception can contain request details.  The processor only
        needs a failure signal, not those details.
        """

        if isinstance(error, (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError, json.JSONDecodeError)):
            return RuntimeError("HTTP request failed")
        return RuntimeError("HTTP request failed")

    def authorize(self, code):
        """Exchange an authorization code and return the provider profile.

        The code is sent as a form-encoded value.  Client credentials are sent
        using HTTP Basic authentication, never in the form body.  The bearer
        token is used only for the subsequent profile request and is not
        returned to the event processor.
        """

        if not isinstance(code, str) or not code.strip():
            raise RuntimeError("authorization failed")

        try:
            form = urlencode(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                }
            ).encode("utf-8")
            basic_value = f"{self.client_id}:{self.client_secret}".encode("utf-8")
            basic = base64.b64encode(basic_value).decode("ascii")
            token_request = Request(
                self.token_url,
                data=form,
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                method="POST",
            )
            with urlopen(token_request, timeout=self.timeout) as response:
                token_data = self._json_response(response)

            if not isinstance(token_data, dict):
                raise RuntimeError("authorization failed")
            access_token = token_data.get("access_token")
            if not isinstance(access_token, str) or not access_token.strip():
                raise RuntimeError("authorization failed")

            profile_request = Request(
                self.profile_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                method="GET",
            )
            with urlopen(profile_request, timeout=self.timeout) as response:
                profile = self._json_response(response)

            if not isinstance(profile, dict):
                raise RuntimeError("authorization failed")
            provider_id = profile.get("id")
            if not isinstance(provider_id, str) or not provider_id.strip():
                raise RuntimeError("authorization failed")
            return profile
        except Exception as error:
            # Do not expose codes, client secrets, access tokens, or endpoint
            # details through an exception that a caller might serialize.
            if isinstance(error, RuntimeError) and str(error) == "authorization failed":
                raise
            raise self._request_error(error) from None

    def send_conversion(self, platform, payload, key):
        """POST a normalized conversion payload to a configured connector."""

        if not isinstance(platform, str) or not platform:
            raise RuntimeError("conversion request failed")
        if not isinstance(key, str) or not key:
            raise RuntimeError("conversion request failed")
        if not isinstance(payload, dict):
            raise RuntimeError("conversion request failed")

        url = self.conversion_urls.get(platform)
        if not isinstance(url, str) or not url:
            raise RuntimeError("conversion request failed")

        try:
            body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
            request = Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Idempotency-Key": key,
                },
                method="POST",
            )
            with urlopen(request, timeout=self.timeout) as response:
                return self._json_response(response)
        except Exception as error:
            if isinstance(error, RuntimeError) and str(error) == "conversion request failed":
                raise
            raise self._request_error(error) from None


__all__ = ["SmartlinkClient"]

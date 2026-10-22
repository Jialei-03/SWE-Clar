"""Small standard-library client for the synthetic music provider.

The client deliberately keeps provider credentials in memory only.  The workflow
stores the provider-facing profile information in business state, while this
object owns the access tokens needed for subsequent library requests.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REQUIRED_LIBRARY_SCOPE = "user-library-modify"


class MusicClientError(RuntimeError):
    """Raised when a provider operation cannot be completed.

    Error details are intentionally kept out of the workflow response.  In
    particular, provider response bodies and access tokens must not become
    part of returned business state.
    """


class MusicClient:
    def __init__(
        self,
        token_url: str,
        api_base: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> None:
        self.token_url = token_url
        self.api_base = api_base.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        # listener_id -> bearer token.  This is deliberately not returned by
        # process_presave_action and is only valid for this client session.
        self._credentials: dict[str, str] = {}

    @staticmethod
    def _json_response(response: Any) -> dict[str, Any]:
        try:
            raw = response.read()
            value = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise MusicClientError("invalid provider response") from exc
        if not isinstance(value, dict):
            raise MusicClientError("invalid provider response")
        return value

    @staticmethod
    def _raise_http(exc: Exception) -> None:
        # Do not include the provider body or URL in the exception text: those
        # values can contain sensitive material and are not useful to callers.
        if isinstance(exc, HTTPError):
            raise MusicClientError("provider request failed") from exc
        if isinstance(exc, (URLError, TimeoutError, OSError)):
            raise MusicClientError("provider unavailable") from exc
        raise MusicClientError("provider request failed") from exc

    def _open(self, request: Request) -> Any:
        try:
            return urlopen(request, timeout=10)
        except Exception as exc:  # urllib has several transport exceptions.
            self._raise_http(exc)
        raise MusicClientError("provider request failed")  # pragma: no cover

    def authorize_listener(self, listener_id: str, code: str) -> dict[str, Any]:
        """Exchange an authorization code and look up the provider profile.

        The token request uses the authorization-code grant and HTTP Basic
        client authentication.  The token is not retained until both the
        exchange and authenticated profile lookup have succeeded.  A grant
        without the library-modify scope is returned to the workflow as an
        unsuccessful authorization, but does not replace an existing token.
        """

        form = urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
            }
        ).encode("utf-8")
        basic = base64.b64encode(
            (f"{self.client_id}:{self.client_secret}").encode("utf-8")
        ).decode("ascii")
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

        try:
            with self._open(token_request) as response:
                if response.getcode() != 200:
                    raise MusicClientError("token exchange failed")
                token_payload = self._json_response(response)
        except MusicClientError:
            raise
        except Exception as exc:
            self._raise_http(exc)

        access_token = token_payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise MusicClientError("token exchange failed")

        raw_scope = token_payload.get("scope", "")
        if isinstance(raw_scope, str):
            scopes = raw_scope.split()
        else:
            scopes = []

        # The profile lookup is required even when the grant lacks the
        # business scope.  It proves that the bearer token is authenticated,
        # but the token is only committed below for an acceptable grant.
        profile_request = Request(
            f"{self.api_base}/me",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with self._open(profile_request) as response:
                if response.getcode() != 200:
                    raise MusicClientError("profile lookup failed")
                profile_payload = self._json_response(response)
        except MusicClientError:
            raise
        except Exception as exc:
            self._raise_http(exc)

        provider_user_id = profile_payload.get("id")
        if not isinstance(provider_user_id, str) or not provider_user_id:
            raise MusicClientError("profile lookup failed")

        # A missing required scope is not an acceptable listener grant.  Do
        # not replace a previous usable token in that case.  The workflow also
        # performs this check against the returned provider scopes before it
        # writes listener business state.
        if REQUIRED_LIBRARY_SCOPE in scopes:
            self._credentials[listener_id] = access_token

        return {
            "provider_user_id": provider_user_id,
            "scopes": list(scopes),
        }

    def save_track(self, listener_id: str, uri: str) -> bool:
        """Save one URI, acknowledging success only for HTTP 200."""

        access_token = self._credentials.get(listener_id)
        if not isinstance(access_token, str) or not access_token:
            raise MusicClientError("missing listener credential")

        # urlencode encodes the complete URI as the query value (including
        # both colons), while leaving the provider path unchanged.
        query = urlencode({"uris": uri})
        request = Request(
            f"{self.api_base}/me/library?{query}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            method="PUT",
        )
        try:
            with self._open(request) as response:
                # The provider contract specifically uses 200 as the
                # acknowledgement.  Do not accept other 2xx statuses.
                if response.getcode() != 200:
                    raise MusicClientError("library save failed")
                # Consume a possible response body before closing it.
                response.read()
        except MusicClientError:
            raise
        except Exception as exc:
            self._raise_http(exc)
        return True

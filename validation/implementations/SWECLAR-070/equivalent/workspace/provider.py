"""Small client for the two provider endpoints used by the estimator.

The provider response is deliberately normalised here.  Nothing returned by a
provider (apart from the fields used by the estimator) is allowed to become a
stored application record.
"""

import json
import math
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Provider keys are query parameters.  Never follow a redirect which
        # could carry one to a host outside the configured loopback service.
        return None


def _invalid():
    raise ValueError("invalid_provider_response")


def number(value, low, high):
    """Return a finite JSON number within the supplied inclusive range."""
    # bool is an int in Python, but is not a geographic number.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid_number")
    try:
        valid = math.isfinite(value) and low <= value <= high
    except (OverflowError, TypeError):
        valid = False
    if not valid:
        raise ValueError("invalid_number")
    return value


def location(point):
    """Validate a Solar-style ``latitude``/``longitude`` object."""
    if not isinstance(point, dict):
        _invalid()
    try:
        latitude = number(point["latitude"], -90, 90)
        longitude = number(point["longitude"], -180, 180)
    except (KeyError, TypeError):
        _invalid()
    return {"latitude": latitude, "longitude": longitude}


def _geocoding_location(point):
    if not isinstance(point, dict):
        _invalid()
    try:
        latitude = number(point["lat"], -90, 90)
        longitude = number(point["lng"], -180, 180)
    except (KeyError, TypeError):
        _invalid()
    return latitude, longitude


def _partial_match_is_valid(value):
    # Google uses a boolean here.  Treat a malformed flag as malformed input
    # rather than silently accepting a possibly ambiguous result.
    if not isinstance(value, bool):
        _invalid()
    return value


def _box(value, center):
    if not isinstance(value, dict):
        _invalid()
    try:
        south_west = location(value["sw"])
        north_east = location(value["ne"])
    except (KeyError, TypeError):
        _invalid()

    if (
        not south_west["latitude"] < north_east["latitude"]
        or not south_west["longitude"] < north_east["longitude"]
        or not south_west["latitude"] <= center["latitude"] <= north_east["latitude"]
        or not south_west["longitude"] <= center["longitude"] <= north_east["longitude"]
    ):
        _invalid()
    return {"sw": south_west, "ne": north_east}


class SolarClient:
    def __init__(self, config):
        if not isinstance(config, dict):
            raise ValueError("invalid_provider_config")
        self.config = config
        self.endpoints = {}
        for name in ("geocoding_url", "solar_url"):
            url = config.get(name)
            if not isinstance(url, str):
                raise ValueError("invalid_provider_config")
            parts = None
            try:
                parts = urlsplit(url)
                host = parts.hostname.lower() if parts.hostname else None
            except (TypeError, ValueError):
                host = None
            if (
                parts is None
                or parts.scheme not in {"http", "https"}
                or host not in _LOOPBACK_HOSTS
                or parts.username is not None
                or parts.password is not None
            ):
                raise ValueError("benchmark_endpoint_must_be_local")
            self.endpoints[name] = url

        key = config.get("api_key")
        if not isinstance(key, str) or not key:
            raise ValueError("invalid_provider_config")
        # Keep the key only in this client.  It is never included in a
        # detection payload, response, or application log.
        self.api_key = key

    def get(self, url, params):
        """GET a JSON object without using ambient proxy configuration."""
        if not isinstance(params, dict):
            raise ValueError("provider_request_failed")
        try:
            parts = urlsplit(url)
            query = [
                (key, value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True)
                if key != "key"
            ]
            for key, value in params.items():
                if str(key) != "key":
                    query.append((str(key), str(value)))
            query.append(("key", self.api_key))
            target = urlunsplit(
                (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
            )
            request = Request(target, method="GET")
            # An empty ProxyHandler prevents a machine-level proxy from
            # turning a loopback benchmark request into an external request.
            opener = build_opener(ProxyHandler({}), _NoRedirect())
            with opener.open(request, timeout=3) as response:
                status = getattr(response, "status", 200)
                if not isinstance(status, int) or not 200 <= status < 300:
                    raise ValueError("provider_request_failed")
                raw = response.read()
            value = json.loads(raw)
        except Exception:
            # Do not propagate an HTTP URL (which contains the API key) in an
            # exception that a caller might log.
            raise ValueError("provider_request_failed") from None
        if not isinstance(value, dict):
            raise ValueError("invalid_provider_response")
        return value

    def find(self, address):
        """Resolve *address* and return the minimal normalised detection."""
        if not isinstance(address, str) or not address.strip():
            raise ValueError("invalid_address")
        submitted_address = address.strip()

        geocoding = self.get(
            self.endpoints["geocoding_url"], {"address": submitted_address}
        )
        if geocoding.get("status") != "OK":
            raise ValueError("address_not_found")
        if "partial_match" in geocoding and _partial_match_is_valid(
            geocoding["partial_match"]
        ):
            raise ValueError("ambiguous_address")
        results = geocoding.get("results")
        if not isinstance(results, list) or len(results) != 1:
            raise ValueError("ambiguous_address")
        result = results[0]
        if not isinstance(result, dict):
            _invalid()
        if "partial_match" in result and _partial_match_is_valid(result["partial_match"]):
            raise ValueError("ambiguous_address")
        try:
            geocoding_point = _geocoding_location(result["geometry"]["location"])
        except (KeyError, TypeError):
            _invalid()

        solar = self.get(
            self.endpoints["solar_url"],
            {
                "location.latitude": geocoding_point[0],
                "location.longitude": geocoding_point[1],
            },
        )
        if "status" in solar and solar.get("status") != "OK":
            raise ValueError("provider_request_failed")
        try:
            center = location(solar["center"])
            bounds = _box(solar["boundingBox"], center)
            area = solar["solarPotential"]["wholeRoofStats"]["areaMeters2"]
            # Area is a JSON number, not a string, and must be finite and
            # strictly positive.  There is intentionally no invented upper
            # bound: the provider owns the modelled area.
            if isinstance(area, bool) or not isinstance(area, (int, float)):
                _invalid()
            try:
                valid_area = math.isfinite(area) and area > 0
            except (OverflowError, TypeError):
                valid_area = False
            if not valid_area:
                _invalid()
        except (KeyError, TypeError):
            _invalid()

        return {
            "address": submitted_address,
            "area_m2": area,
            "center": center,
            "bounds": bounds,
        }

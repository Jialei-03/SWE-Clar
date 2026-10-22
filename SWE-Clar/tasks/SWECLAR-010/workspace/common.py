"""Public transport validation and canonical page URL helpers."""
import re
from urllib.parse import urlsplit, urlunsplit


class Problem(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def require(condition, code='invalid', status=400):
    if not condition:
        raise Problem(status, code)


def fields(value, names):
    require(isinstance(value, dict) and set(value) == set(names))


def ident(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value) is not None


def timestamp(value):
    return type(value) is int and 0 <= value <= 253402300799999


def name(value):
    require(isinstance(value, str))
    value = value.strip()
    require(0 < len(value) <= 120)
    return value


def pairs(items):
    out = {}
    for key, value in items:
        require(key not in out, 'duplicate_json_key')
        out[key] = value
    return out


def invalid_constant(_):
    raise ValueError('JSON nonfinite constant')


def canonical_url(value, provider):
    require(isinstance(value, str) and 0 < len(value) <= 2048)
    require(not any(c.isspace() for c in value))
    try:
        url, allowed = urlsplit(value), urlsplit(provider)
        require(url.scheme.lower() == 'http' and url.hostname == allowed.hostname and (url.port or 80) == (allowed.port or 80))
        require(url.username is None and url.password is None)
        require(url.path.startswith('/pages/') and ident(url.path[7:]))
        host = url.hostname.lower()
        authority = host + (':'+str(url.port) if url.port and url.port != 80 else '')
        return urlunsplit(('http', authority, url.path, url.query, ''))
    except ValueError:
        raise Problem(400, 'invalid_url')

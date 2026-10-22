"""Small validation and error helpers shared by the HTTP application."""
import re


class Problem(Exception):
    def __init__(self, status, code):
        self.status = status
        self.code = code
        super().__init__(code)


def require(condition, code="invalid", status=400):
    if not condition:
        raise Problem(status, code)


def fields(value, names):
    """Require a JSON object with exactly the named fields."""
    require(isinstance(value, dict) and set(value) == set(names))


def optional_fields(value, allowed, required=()):
    """Validate a query object represented by a dict of single values."""
    require(isinstance(value, dict))
    require(set(value).issubset(set(allowed)))
    require(set(required).issubset(set(value)))


_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def ident(value):
    return isinstance(value, str) and _ID_RE.fullmatch(value) is not None


def timestamp(value):
    # bool is an int subclass, but it is not a public timestamp.
    return type(value) is int and 0 <= value <= 253402300799999


def text(value, limit, nonempty=True, trim=True):
    require(isinstance(value, str))
    # JSON can spell an unpaired UTF-16 surrogate even though it is not a
    # Unicode scalar value and cannot be persisted or rendered as UTF-8.
    require(not any(0xD800 <= ord(character) <= 0xDFFF for character in value))
    result = value.strip() if trim else value
    require(len(result) <= limit and (bool(result) or not nonempty))
    return result

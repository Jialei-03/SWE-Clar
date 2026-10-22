"""Canonical JSON serialization and content digest helpers."""

import hashlib

import rfc8785


def normalize(value: object) -> object:
    """Normalize text line endings recursively before serialization."""
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\r", "\n")
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    return value


def canonical_bytes(value: object) -> bytes:
    """Return RFC 8785 canonical JSON bytes for a normalized value."""
    return rfc8785.dumps(normalize(value))


def digest_json(value: object) -> str:
    """Return a prefixed SHA-256 digest of canonical JSON bytes."""
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def digest_bytes(value: bytes) -> str:
    """Return a prefixed SHA-256 digest of exact input bytes."""
    return "sha256:" + hashlib.sha256(value).hexdigest()

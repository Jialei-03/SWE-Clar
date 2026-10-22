"""Immutable content-addressed artifact storage."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, digest_bytes


_DIGEST_PATTERN = re.compile(r"sha256:([0-9a-f]{64})\Z")


class ArtifactError(Exception):
    """Base class for artifact store failures."""


class InvalidArtifactDigest(ArtifactError, ValueError):
    """Raised when a digest is not a strict SHA-256 identifier."""


class ArtifactNotFound(ArtifactError, FileNotFoundError):
    """Raised when a valid artifact identifier is absent."""


class ArtifactCorrupt(ArtifactError):
    """Raised when stored bytes do not match their content identifier."""


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    digest: str
    size: int


class ArtifactStore:
    """Store immutable bytes below a trusted root, addressed by SHA-256."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)

    def put_bytes(self, data: bytes) -> ArtifactRef:
        if not isinstance(data, bytes):
            raise TypeError("artifact data must be bytes")

        digest = digest_bytes(data)
        destination = self._path_for_digest(digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            self._verify_existing(destination, digest, data)
            return ArtifactRef(digest=digest, size=len(data))

        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())

            if destination.exists():
                self._verify_existing(destination, digest, data)
            else:
                os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

        return ArtifactRef(digest=digest, size=len(data))

    def put_json(self, value: object) -> ArtifactRef:
        return self.put_bytes(canonical_bytes(value))

    def get_bytes(self, digest: str) -> bytes:
        path = self._path_for_digest(digest)
        try:
            data = path.read_bytes()
        except FileNotFoundError as error:
            raise ArtifactNotFound(f"artifact not found: {digest}") from error
        if digest_bytes(data) != digest:
            raise ArtifactCorrupt(f"artifact content does not match digest: {digest}")
        return data

    def get_json(self, digest: str) -> Any:
        data = self.get_bytes(digest)
        try:
            value = json.loads(data)
            if canonical_bytes(value) != data:
                raise ArtifactCorrupt(f"artifact is not canonical JSON: {digest}")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise ArtifactCorrupt(f"artifact is not canonical JSON: {digest}") from error
        return value

    def _path_for_digest(self, digest: str) -> Path:
        if not isinstance(digest, str):
            raise InvalidArtifactDigest("artifact digest must be a string")
        match = _DIGEST_PATTERN.fullmatch(digest)
        if match is None:
            raise InvalidArtifactDigest(f"invalid artifact digest: {digest!r}")
        hexadecimal = match.group(1)
        return self.root / "sha256" / hexadecimal[:2] / hexadecimal[2:]

    @staticmethod
    def _verify_existing(path: Path, digest: str, expected: bytes) -> None:
        try:
            stored = path.read_bytes()
        except OSError as error:
            raise ArtifactCorrupt(f"cannot read existing artifact: {digest}") from error
        if stored != expected or digest_bytes(stored) != digest:
            raise ArtifactCorrupt(f"existing artifact is corrupt: {digest}")

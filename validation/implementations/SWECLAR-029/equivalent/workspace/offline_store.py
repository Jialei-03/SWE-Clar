"""Encrypted on-device storage for field-work bundles.

The public store deliberately keeps all encryption material on the store object.
Only the encrypted bundle is written to disk; the caller owns the key and the
returned metadata contains no sensitive bundle contents.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_HEADER = b"FS1"
_NONCE_SIZE = 12
_TAG_SIZE = 16


def _compact_json(value: Any) -> bytes:
    """Return the canonical JSON representation used by the store."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _identity_json(value: Any) -> bytes:
    """Encode an identifier without introducing whitespace or ASCII escapes."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class OfflineStore:
    """Store AES-GCM protected job bundles below ``root``.

    Bundle names are derived from the user and job identifiers rather than
    using the identifiers as path components.  This both prevents path
    traversal and gives ``remove_user`` an unambiguous user directory.  The
    name is not part of the public contract; callers should use the relative
    path returned by :meth:`write_bundle`.
    """

    def __init__(self, root, key):
        self.root = Path(root)
        self.key = bytes(key)
        if len(self.key) not in (16, 24, 32):
            raise ValueError("AES key must be 16, 24, or 32 bytes")

    @staticmethod
    def _token(value: Any) -> str:
        return hashlib.sha256(_identity_json(value)).hexdigest()

    def _user_directory(self, user_id: Any) -> Path:
        return self.root / ("u-" + self._token(user_id))

    def _bundle_path(self, user_id: Any, job_id: Any) -> Path:
        return self._user_directory(user_id) / ("j-" + self._token(job_id) + ".fs1")

    def _relative_path(self, path: Path) -> str:
        # ``root`` is the only storage root used by this class, so this is
        # always a root-relative path even when the caller supplied a relative
        # root.  POSIX separators make metadata stable in JSON as well.
        return path.relative_to(self.root).as_posix()

    @staticmethod
    def _associated_data(user_id: Any, job_id: Any) -> bytes:
        # This exact representation is also used by read_bundle.  It is
        # intentionally not the path token: changing either identifier must
        # invalidate authentication even if a file is copied to another name.
        return _compact_json([user_id, job_id])

    def write_bundle(self, user_id, job_id, data):
        """Serialize and atomically write one authenticated encrypted bundle.

        The returned metadata describes the plaintext size and digest, while
        ``path`` is relative to this store's root.  A fresh nonce is used on
        every write, including a redownload of the same job.
        """

        plaintext = _compact_json(data)
        digest = hashlib.sha256(plaintext).hexdigest()
        nonce = os.urandom(_NONCE_SIZE)
        ciphertext_and_tag = AESGCM(self.key).encrypt(
            nonce,
            plaintext,
            self._associated_data(user_id, job_id),
        )
        blob = _HEADER + nonce + ciphertext_and_tag

        path = self._bundle_path(user_id, job_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Replace rather than append so a redownload cannot leave a second
        # plaintext-size contribution or an old unauthenticated file around.
        fd, temporary_name = tempfile.mkstemp(
            prefix=".bundle-",
            suffix=".tmp",
            dir=str(path.parent),
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(blob)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temporary_path, 0o600)
            except OSError:
                # Permissions are a defense in depth measure.  The encrypted
                # format and atomic replacement remain the correctness rules.
                pass
            os.replace(temporary_path, path)
        except Exception:
            try:
                temporary_path.unlink()
            except OSError:
                pass
            raise

        return {
            "size_bytes": len(plaintext),
            "sha256": digest,
            "encrypted": True,
            "path": self._relative_path(path),
        }

    def read_bundle(self, user_id, job_id):
        """Read and authenticate a bundle for exactly this user/job pair."""

        path = self._bundle_path(user_id, job_id)
        blob = path.read_bytes()
        minimum_size = len(_HEADER) + _NONCE_SIZE + _TAG_SIZE
        if len(blob) < minimum_size or blob[: len(_HEADER)] != _HEADER:
            raise ValueError("invalid bundle format")

        nonce_start = len(_HEADER)
        nonce = blob[nonce_start : nonce_start + _NONCE_SIZE]
        ciphertext_and_tag = blob[nonce_start + _NONCE_SIZE :]
        # AESGCM raises InvalidTag for tampering, a wrong key, or a copied
        # bundle whose associated user/job does not match.
        plaintext = AESGCM(self.key).decrypt(
            nonce,
            ciphertext_and_tag,
            self._associated_data(user_id, job_id),
        )
        return json.loads(plaintext.decode("utf-8"))

    def remove_user(self, user_id):
        """Remove all bundles belonging to one user and no other user."""

        directory = self._user_directory(user_id)
        if directory.exists():
            # rmtree propagates deletion errors so logout can report failure
            # instead of claiming that cleanup succeeded.
            shutil.rmtree(directory)

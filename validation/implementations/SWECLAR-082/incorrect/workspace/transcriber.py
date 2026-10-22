"""Local, isolated PCM-WAV speech transcription using whisper.cpp."""

from __future__ import annotations

from array import array
from pathlib import Path
import hashlib
import io
import subprocess
import sys
import tempfile
import wave
from typing import Any


class LocalWhisper:
    """Validate asset-local WAV files and run a local whisper.cpp binary.

    ``asset_root`` is the trust boundary.  The action supplies a relative path;
    resolution is performed before every read so a ``..`` component or a
    symlink pointing outside the directory is rejected.
    """

    def __init__(self, binary: str | Path, model: str | Path, asset_root: str | Path):
        self.binary = str(binary)
        self.model = str(model)
        self.root = Path(asset_root).resolve()

    def _resolve(self, relative: Any) -> Path:
        if not isinstance(relative, str) or not relative or "\x00" in relative:
            raise ValueError("invalid audio path")
        candidate = Path(relative)
        # Absolute paths are not an alternate spelling for asset-local paths,
        # even when they happen to point below the root.
        if candidate.is_absolute():
            raise ValueError("audio path must be relative")
        try:
            resolved = (self.root / candidate).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError("invalid audio path") from exc
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("audio path outside asset root") from exc
        if not resolved.is_file():
            raise ValueError("invalid audio file")
        return resolved

    @staticmethod
    def _validate_wav(data: bytes) -> None:
        """Validate the exact PCM bytes required by the session service."""

        try:
            with wave.open(io.BytesIO(data), "rb") as wav:
                if (
                    wav.getnchannels() != 1
                    or wav.getsampwidth() != 2
                    or wav.getframerate() != 16000
                    or wav.getcomptype() != "NONE"
                ):
                    raise ValueError("unsupported audio format")
                frames = wav.getnframes()
                if not 1 <= frames <= 480000:
                    raise ValueError("unsupported audio length")
                pcm = wav.readframes(frames)
                if len(pcm) != frames * 2:
                    raise ValueError("truncated audio")
        except (wave.Error, EOFError, OSError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc) in {
                "unsupported audio format",
                "unsupported audio length",
                "truncated audio",
                "no audible speech",
            }:
                raise
            raise ValueError("malformed WAV audio") from exc

        # PCM WAV samples are little-endian signed 16-bit values.  array keeps
        # this check independent of the host byte order.
        samples = array("h")
        try:
            samples.frombytes(pcm)
        except (OverflowError, ValueError) as exc:
            raise ValueError("malformed PCM audio") from exc
        if sys.byteorder != "little":
            samples.byteswap()
        if not samples or max(abs(sample) for sample in samples) < 20:
            raise ValueError("no audible speech")

    def _read_validated(self, relative: Any) -> tuple[Path, bytes]:
        path = self._resolve(relative)
        try:
            data = path.read_bytes()
        except (OSError, ValueError) as exc:
            raise ValueError("cannot read audio") from exc
        self._validate_wav(data)
        return path, data

    def audio(self, relative: Any) -> Path:
        """Validate an asset-local WAV and return its resolved path."""

        path, _ = self._read_validated(relative)
        return path

    def audio_digest(self, relative: Any) -> str:
        """Return the SHA-256 of the validated WAV file bytes."""

        _, data = self._read_validated(relative)
        return hashlib.sha256(data).hexdigest()

    def transcribe(self, relative: Any) -> str:
        """Run whisper.cpp locally and return its generated text.

        The model and executable are supplied by the operator; this method has
        no network or download path.  A temporary output directory prevents
        whisper's text output from becoming a customer asset.
        """

        path, _ = self._read_validated(relative)
        with tempfile.TemporaryDirectory(prefix="clarswe-whisper-") as directory:
            output_prefix = Path(directory) / "transcription"
            command = [
                self.binary,
                "-m",
                self.model,
                "-f",
                str(path),
                "-t",
                "2",
                "-l",
                "en",
                "-otxt",
                "-of",
                str(output_prefix),
            ]
            try:
                completed = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                    timeout=120,
                )
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                raise RuntimeError("local whisper failed") from exc
            if completed.returncode != 0:
                raise RuntimeError("local whisper failed")

            output_file = output_prefix.with_suffix(".txt")
            try:
                text = output_file.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise RuntimeError("local whisper produced no text") from exc
            if not text.strip():
                raise RuntimeError("local whisper produced no speech")
            return text

"""MediaMTX/FFmpeg integration for direct, loopback-only event streams.

The media process is deliberately owned by this application.  A start creates a
small, per-event MediaMTX instance with one exact path.  MediaMTX records the
publisher's stream; no URL supplied by an HTTP caller is ever used as a source.
"""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote


class MediaError(RuntimeError):
    """Raised when an actual stream cannot be started or finalized."""


def _free_port() -> int:
    """Return an unused loopback TCP port.

    The socket is released before MediaMTX starts.  The short race is harmless:
    begin() checks that the child successfully owns the port before returning.
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_listener(process: subprocess.Popen[bytes], port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise MediaError("media_service_stopped")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.05)
    raise MediaError("media_service_timeout")


def _stop_process(process: subprocess.Popen[bytes], timeout: float = 15.0) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired as exc:  # pragma: no cover - pathological OS failure
            raise MediaError("media_service_wont_stop") from exc


def _run_checked(command: list[str], timeout: float, error: str) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaError(error) from exc
    if result.returncode != 0:
        raise MediaError(error)
    return result


class Media:
    """Own MediaMTX children and turn their recordings into immutable MP4s."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        # Do not put configuration or active recordings in the public storage
        # namespace.  Finalized files are moved beneath self.root only after
        # they have been decoded and measured.
        self.root = self.root.resolve()
        self.active: dict[str, dict[str, Any]] = {}
        self._workspace = Path(tempfile.mkdtemp(prefix="event-video-media-"))
        self._workspace.chmod(0o700)
        self._closed = False

    @staticmethod
    def _safe_component(value: str) -> str:
        if not isinstance(value, str) or not value or len(value) > 128:
            raise MediaError("invalid_event")
        if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
            raise MediaError("invalid_event")
        return value

    def begin(self, event: str, key: str) -> dict[str, str]:
        """Start an authenticated direct publisher path for *event*."""

        if self._closed:
            raise MediaError("media_closed")
        event = self._safe_component(event)
        if not isinstance(key, str) or not key:
            raise MediaError("invalid_stream_key")
        if event in self.active:
            raise MediaError("already_live")

        rtmp_port = _free_port()
        hls_port = _free_port()
        while hls_port == rtmp_port:
            hls_port = _free_port()
        # A path capability prevents arbitrary path publishing even before the
        # RTMP username/password check.  The configured stream key is never put
        # in a URL or in a MediaMTX configuration.
        path_capability = secrets.token_hex(24)
        username = "publisher"
        password = secrets.token_hex(32)
        work = self._workspace / event / path_capability
        records = work / "records"
        records.mkdir(parents=True, exist_ok=True)
        config_path = work / "mediamtx.json"
        log_path = work / "mediamtx.log"

        # The anonymous read identity is limited to this exact path.  The
        # publisher identity has publish permission only for the same path.
        # MediaMTX's RTMP listener therefore rejects an omitted, wrong, or
        # modified publisher credential at the actual handshake.
        config = {
            "logLevel": "warn",
            "rtsp": False,
            "rtmp": True,
            "rtmpAddress": f"127.0.0.1:{rtmp_port}",
            "hls": True,
            "hlsAddress": f"127.0.0.1:{hls_port}",
            "hlsVariant": "mpegts",
            "hlsAlwaysRemux": True,
            "hlsSegmentDuration": "1s",
            "webrtc": False,
            "srt": False,
            "moq": False,
            "api": False,
            "metrics": False,
            "pprof": False,
            "authMethod": "internal",
            "authInternalUsers": [
                # Put the credentialed publisher before the anonymous `any`
                # reader: MediaMTX evaluates the first matching identity.
                {
                    "user": username,
                    "pass": password,
                    "ips": [],
                    "permissions": [{"action": "publish", "path": path_capability}],
                },
                {
                    "user": "any",
                    "pass": "",
                    "ips": [],
                    "permissions": [{"action": "read", "path": path_capability}],
                },
            ],
            "pathDefaults": {
                "record": True,
                "recordPath": str(records / "%path" / "%Y-%m-%d_%H-%M-%S-%f"),
                "recordDeleteAfter": "0s",
                # Use short owned segments so even a brief but real synthetic
                # stream leaves finalized media before the child is stopped.
                # end() joins those MP4 segments into one archive.
                "recordSegmentDuration": "500ms",
            },
            "paths": {path_capability: {"source": "publisher"}},
        }
        config_path.write_text(json.dumps(config), encoding="utf-8")
        config_path.chmod(0o600)
        log = log_path.open("ab")
        binary = os.environ.get("MEDIAMTX_BIN", "mediamtx")
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                [binary, str(config_path)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
            )
            _wait_for_listener(process, rtmp_port)
        except Exception:
            if process is not None:
                _stop_process(process)
            log.close()
            shutil.rmtree(work, ignore_errors=True)
            raise

        self.active[event] = {
            "process": process,
            "log": log,
            "config": config_path,
            "work": work,
            "records": records,
            "capability": path_capability,
            "username": username,
            "password": password,
            "rtmp_port": rtmp_port,
            "hls_port": hls_port,
        }
        return {
            # MediaMTX's RTMP challenge reads credentials from these query
            # fields (rather than URL userinfo, which FFmpeg does not forward
            # as RTMP connect parameters).  They are random capabilities, not
            # the configured event key.
            "ingest_url": (
                f"rtmp://127.0.0.1:{rtmp_port}/{path_capability}"
                f"?user={quote(username, safe='')}&pass={quote(password, safe='')}"
            ),
            "hls_url": f"http://127.0.0.1:{hls_port}/{path_capability}/index.m3u8",
        }

    def _raw_files(self, item: dict[str, Any]) -> list[Path]:
        records = item["records"]
        # MediaMTX writes finalized recordings with an .mp4 suffix even though
        # recordPath is a timestamp template without one.
        return sorted(
            (p for p in records.rglob("*.mp4") if p.is_file() and not p.is_symlink()),
            # The timestamp template is the recording order.  File mtimes can
            # be inverted when MediaMTX closes two short segments together.
            key=lambda p: p.name,
        )

    def _measure_and_validate(self, path: Path) -> dict[str, Any]:
        if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
            raise MediaError("empty_recording")
        ffprobe = os.environ.get("FFPROBE_BIN", "ffprobe")
        ffmpeg = os.environ.get("FFMPEG_BIN", "ffmpeg")
        probe = _run_checked(
            [
                ffprobe,
                "-v",
                "error",
                "-count_frames",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            30,
            "invalid_recording",
        )
        try:
            document = json.loads(probe.stdout)
            streams = document.get("streams") or []
            video = next(stream for stream in streams if stream.get("codec_type") == "video")
            frames_value = video.get("nb_read_frames", video.get("nb_frames"))
            frames = int(frames_value) if frames_value not in (None, "N/A", "") else 0
            fmt_duration = (document.get("format") or {}).get("duration")
            stream_duration = video.get("duration")
            duration_value = fmt_duration if fmt_duration not in (None, "N/A", "") else stream_duration
            duration = float(duration_value) if duration_value not in (None, "N/A", "") else 0.0
        except (ValueError, TypeError, StopIteration, json.JSONDecodeError) as exc:
            raise MediaError("invalid_recording") from exc
        if frames <= 0 or duration <= 0 or not math.isfinite(duration):
            raise MediaError("empty_recording")

        # ffprobe metadata alone is not evidence of a decodable recording.
        _run_checked(
            [
                ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-f",
                "null",
                "-",
            ],
            60,
            "undecodable_recording",
        )
        size = path.stat().st_size
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return {
            "path": str(path),
            "bytes": int(size),
            "sha256": digest.hexdigest(),
            "duration": duration,
            "frames": frames,
        }

    def end(self, event: str) -> dict[str, Any]:
        event = self._safe_component(event)
        item = self.active.pop(event, None)
        if item is None:
            raise MediaError("not_live")
        process = item["process"]
        try:
            _stop_process(process)
            item["log"].close()

            raw = self._raw_files(item)
            if not raw:
                raise MediaError("empty_recording")

            # A normal event is one record segment.  If a very long stream was
            # split by MediaMTX, concatenate its independently finalized MP4
            # segments before measuring the archive.
            source = raw[0]
            if len(raw) > 1:
                ffmpeg = os.environ.get("FFMPEG_BIN", "ffmpeg")
                concat_list = item["work"] / "concat.txt"
                concat_list.write_text(
                    "".join(
                        "file '" + str(path).replace("'", "'\\''") + "'\n"
                        for path in raw
                    ),
                    encoding="utf-8",
                )
                combined = item["work"] / "combined.mp4"
                try:
                    _run_checked(
                        [
                            ffmpeg,
                            "-nostdin",
                            "-v",
                            "error",
                            "-f",
                            "concat",
                            "-safe",
                            "0",
                            "-i",
                            str(concat_list),
                            "-c",
                            "copy",
                            "-movflags",
                            "+faststart",
                            str(combined),
                        ],
                        60,
                        "recording_join_failed",
                    )
                    source = combined
                except MediaError:
                    # A publisher can disconnect while a final short segment
                    # is being closed.  A single valid segment is still real,
                    # decodable captured media; never manufacture metadata for
                    # an invalid join.
                    source = max(raw, key=lambda path: path.stat().st_size)

            measured = self._measure_and_validate(source)
            final_dir = self.root / "archives"
            final_dir.mkdir(parents=True, exist_ok=True)
            final = final_dir / f"{event}-{secrets.token_hex(16)}.mp4"
            try:
                os.replace(source, final)
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    raise
                # The service workspace is intentionally in private /tmp,
                # while a host may configure durable storage on /workspace or
                # another mount.  Install through a same-filesystem staging
                # file without ever publishing a partial MP4.
                staging = final.with_name(final.name + ".part")
                try:
                    with source.open("rb") as source_file, staging.open("wb") as target:
                        shutil.copyfileobj(source_file, target, length=1024 * 1024)
                        target.flush()
                        os.fsync(target.fileno())
                    os.replace(staging, final)
                    source.unlink()
                finally:
                    staging.unlink(missing_ok=True)
            measured["path"] = str(final)
            return measured
        finally:
            # The process is no longer needed, and raw media/configuration is
            # not part of the durable archive namespace.
            try:
                item["log"].close()
            except Exception:
                pass
            shutil.rmtree(item["work"], ignore_errors=True)

    def abort(self, event: str) -> None:
        """Stop and discard a stream when its DB transition cannot commit."""

        item = self.active.pop(event, None)
        if item is None:
            return
        try:
            _stop_process(item["process"])
        finally:
            try:
                item["log"].close()
            except Exception:
                pass
            shutil.rmtree(item["work"], ignore_errors=True)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for event in list(self.active):
            self.abort(event)
        shutil.rmtree(self._workspace, ignore_errors=True)

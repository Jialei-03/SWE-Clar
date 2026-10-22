"""Liveness-aware consumption of streamed child-process output.

The Pi Coding Agent streams JSON lines for progress and its final result.  A
normal shell-command timeout does not protect the complete model session: if
the provider stops replying after a tool result, the parent can otherwise
block forever while reading stdout.  This module gives that outer session an
inactivity watchdog and an optional total wall-clock deadline.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import selectors
import signal
import subprocess
import time
from typing import Callable, TextIO


@dataclass(frozen=True)
class ProcessOutcome:
    returncode: int
    stderr: str
    elapsed_s: float
    last_stdout_line: str | None


class StreamedProcessTimeout(TimeoutError):
    kind = "timeout"

    def __init__(
        self,
        *,
        timeout_s: float,
        elapsed_s: float,
        last_stdout_line: str | None,
        stderr: str,
    ) -> None:
        self.timeout_s = timeout_s
        self.elapsed_s = elapsed_s
        self.last_stdout_line = last_stdout_line
        self.stderr = stderr
        super().__init__(
            f"streamed process {self.kind} after {timeout_s:.3f}s "
            f"(elapsed={elapsed_s:.3f}s, last_stdout={last_stdout_line!r})"
        )


class ProcessIdleTimeout(StreamedProcessTimeout):
    kind = "idle timeout"


class ProcessTotalTimeout(StreamedProcessTimeout):
    kind = "total timeout"


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate a child and its process group without hanging the caller."""

    if process.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        process.terminate()
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        process.kill()
    process.wait(timeout=2)


def consume_streamed_process(
    process: subprocess.Popen[str],
    on_stdout_line: Callable[[str], None],
    *,
    idle_timeout_s: float,
    total_timeout_s: float | None,
    max_stderr_chars: int = 64_000,
) -> ProcessOutcome:
    """Consume stdout/stderr until completion or a bounded timeout.

    ``process`` must expose text-mode stdout and stderr pipes.  Any received
    line counts as activity; stdout lines are forwarded immediately while
    stderr is retained as bounded diagnostics.
    """

    if idle_timeout_s <= 0 or (
        total_timeout_s is not None and total_timeout_s <= 0
    ):
        raise ValueError("watchdog timeouts must be positive when configured")
    if process.stdout is None or process.stderr is None:
        raise ValueError("process must have stdout and stderr pipes")

    started = time.monotonic()
    last_activity = started
    last_stdout_line: str | None = None
    stderr_parts: list[str] = []
    selector = selectors.DefaultSelector()
    streams: tuple[tuple[TextIO, str], ...] = (
        (process.stdout, "stdout"),
        (process.stderr, "stderr"),
    )
    for stream, name in streams:
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, data=name)
    pending: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}

    def accept_line(name: str, raw: bytes) -> None:
        nonlocal last_stdout_line, stderr_parts
        line = raw.decode("utf-8", errors="replace")
        if name == "stdout":
            last_stdout_line = line.rstrip("\r\n")
            on_stdout_line(line)
        else:
            stderr_parts.append(line)
            if sum(map(len, stderr_parts)) > max_stderr_chars * 2:
                stderr_parts = ["".join(stderr_parts)[-max_stderr_chars:]]

    try:
        while selector.get_map():
            now = time.monotonic()
            idle_remaining = idle_timeout_s - (now - last_activity)
            total_remaining = (
                None
                if total_timeout_s is None
                else total_timeout_s - (now - started)
            )
            if total_remaining is not None and total_remaining <= 0:
                raise ProcessTotalTimeout(
                    timeout_s=total_timeout_s,
                    elapsed_s=now - started,
                    last_stdout_line=last_stdout_line,
                    stderr="".join(stderr_parts)[-max_stderr_chars:],
                )
            if idle_remaining <= 0:
                raise ProcessIdleTimeout(
                    timeout_s=idle_timeout_s,
                    elapsed_s=now - started,
                    last_stdout_line=last_stdout_line,
                    stderr="".join(stderr_parts)[-max_stderr_chars:],
                )

            select_timeout = (
                idle_remaining
                if total_remaining is None
                else min(idle_remaining, total_remaining)
            )
            events = selector.select(timeout=select_timeout)
            if not events:
                now = time.monotonic()
                error_type = (
                    ProcessTotalTimeout
                    if total_timeout_s is not None
                    and now - started >= total_timeout_s
                    else ProcessIdleTimeout
                )
                timeout_s = (
                    total_timeout_s
                    if error_type is ProcessTotalTimeout
                    else idle_timeout_s
                )
                raise error_type(
                    timeout_s=float(timeout_s),
                    elapsed_s=now - started,
                    last_stdout_line=last_stdout_line,
                    stderr="".join(stderr_parts)[-max_stderr_chars:],
                )

            for key, _mask in events:
                stream = key.fileobj
                # Buffered TextIO.readline can both hide already-read lines
                # from select() and block past the watchdog on a partial line.
                # Read raw nonblocking chunks, then drain every complete line.
                try:
                    chunk = os.read(stream.fileno(), 64 * 1024)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    if pending[key.data]:
                        accept_line(key.data, bytes(pending[key.data]))
                        pending[key.data].clear()
                    continue
                last_activity = time.monotonic()
                pending[key.data].extend(chunk)
                lines = pending[key.data].split(b"\n")
                pending[key.data] = lines.pop()
                for raw in lines:
                    accept_line(key.data, raw + b"\n")
                if key.data == "stderr" and len(pending["stderr"]) > max_stderr_chars:
                    pending["stderr"] = pending["stderr"][-max_stderr_chars:]
    except StreamedProcessTimeout:
        _terminate_process_tree(process)
        raise
    finally:
        selector.close()

    returncode = process.wait(timeout=2)
    elapsed_s = time.monotonic() - started
    return ProcessOutcome(
        returncode=returncode,
        stderr="".join(stderr_parts)[-max_stderr_chars:],
        elapsed_s=elapsed_s,
        last_stdout_line=last_stdout_line,
    )

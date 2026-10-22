"""Admission policy for durable live Pi progress snapshots."""

from __future__ import annotations

from collections.abc import Callable
import time


class ProgressPersistenceGate:
    """Coalesce text previews while preserving semantic event boundaries.

    Pi emits token-stream previews much more frequently than a human or the
    console poller can consume them. Persisting every preview rewrites the
    complete growing Run document and makes long trajectories increasingly
    expensive. Tool and turn events are never coalesced.
    """

    def __init__(
        self,
        *,
        assistant_interval_seconds: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if assistant_interval_seconds <= 0:
            raise ValueError("assistant_interval_seconds must be positive")
        self._assistant_interval_seconds = assistant_interval_seconds
        self._clock = clock
        self._last_assistant_persisted_at: float | None = None

    def should_persist(self, event_name: str) -> bool:
        if event_name != "assistant_update":
            return True
        now = self._clock()
        if (
            self._last_assistant_persisted_at is not None
            and now - self._last_assistant_persisted_at
            < self._assistant_interval_seconds
        ):
            return False
        self._last_assistant_persisted_at = now
        return True

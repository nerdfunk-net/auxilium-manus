"""Fail fast while the Hatchet engine is unreachable.

The SDK retries an unreachable engine for about 17 s before it raises, and the call is synchronous:
every trigger during an outage would hold one of the web server's worker threads for that long
(O2-01). After a failed dispatch the breaker stays open for a short window and the next dispatches
are refused immediately; the first dispatch after the window is a real attempt again, and a
success closes the breaker at once. The state is per process, which is the right scope: each
process has its own threads to protect.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

DEFAULT_OPEN_SECONDS = 15.0

# Shown to the user (a fixed string, never exception text) when a run cannot be handed to Hatchet.
ENGINE_UNAVAILABLE_MESSAGE = "The workflow execution engine is unavailable. Try again in a minute."


class EngineUnavailableError(RuntimeError):
    """Raised instead of calling Hatchet while the breaker is open."""


class DispatchBreaker:
    def __init__(
        self,
        open_seconds: float = DEFAULT_OPEN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._open_seconds = open_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._open_until = 0.0

    def is_open(self) -> bool:
        with self._lock:
            return self._clock() < self._open_until

    def record_failure(self) -> None:
        with self._lock:
            self._open_until = self._clock() + self._open_seconds

    def record_success(self) -> None:
        with self._lock:
            self._open_until = 0.0

    def reset(self) -> None:
        self.record_success()


dispatch_breaker = DispatchBreaker()

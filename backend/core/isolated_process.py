"""Run one job in a killable child process (S4-07).

A Jinja render or a regex match holds the GIL and cannot be interrupted from another thread, so
author-written content that loops or backtracks for ages would stall a worker for good. The child
runs with ``python -I`` and an empty environment (no ``SECRET_KEY``, database or Hatchet
secrets), sets its own CPU and memory limits, and is killed by the parent at the timeout.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# The workflow steps (render-jinja-template, update-config-context, batfish-validate-facts,
# update-content): wall-clock limit per job, and children per worker process. A device that finds
# every slot taken waits for one; it never fails "busy".
STEP_CHILD_SECONDS = 10.0
STEP_CHILD_SLOTS_LIMIT = 4

_POLL_SECONDS = 0.02


class ChildSlots:
    """A per-process cap on concurrent children.

    A counter, not an ``asyncio.Semaphore``: a module-level semaphore binds to the first event loop
    that waits on it, and the tests (and the API) run more than one loop.
    """

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self.active = 0

    @asynccontextmanager
    async def hold(self, *, wait_seconds: float | None) -> AsyncGenerator[bool]:
        """Yield ``True`` while a slot is held, ``False`` when none came free within
        ``wait_seconds`` (``None`` waits as long as it takes)."""
        loop = asyncio.get_running_loop()
        deadline = None if wait_seconds is None else loop.time() + wait_seconds
        while self.active >= self._limit:
            if deadline is not None and loop.time() >= deadline:
                yield False
                return
            await asyncio.sleep(_POLL_SECONDS)
        self.active += 1
        try:
            yield True
        finally:
            self.active -= 1


STEP_CHILD_SLOTS = ChildSlots(STEP_CHILD_SLOTS_LIMIT)


async def run_child(
    worker: Path,
    payload: bytes,
    *,
    timeout: float,
    max_response_bytes: int,
    args: Sequence[str] = (),
) -> bytes | None:
    """The child's stdout, or ``None`` when it could not start, ran past ``timeout``, exited
    with an error or answered more than ``max_response_bytes``. Never guesses a result."""
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(worker),
            *args,
            env={},  # the child must not see SECRET_KEY, database or Hatchet secrets
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        logger.warning("Could not start the isolated worker %s", worker.name, exc_info=True)
        return None
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(payload), timeout=timeout)
    except TimeoutError:
        return None
    finally:
        if process.returncode is None:  # timeout, or the caller was cancelled
            process.kill()
            await process.wait()
    if process.returncode != 0 or len(stdout) > max_response_bytes:
        return None
    return stdout

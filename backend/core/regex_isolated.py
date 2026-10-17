"""Run a user-supplied regular expression in a killable child process (S4-07, S5 correction).

``re`` holds the GIL while it matches, so a pattern such as ``(a+)+$`` on a short input would stall
every request of the API process, not just the one that sent it. The child process has CPU and
memory limits, an empty environment, and is killed on timeout.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_WORKER = Path(__file__).with_name("regex_worker.py")
DEFAULT_TIMEOUT_SECONDS = 2.0
MAX_CONCURRENT_REGEX_JOBS = 4
MAX_RESPONSE_BYTES = 2_500_000
_BUSY_POLL_SECONDS = 0.05

_active = 0

_STOPPED = "The regular expression was stopped: it used too much time or memory"
_BUSY = "The regular expression runner is busy; try again in a moment"


@dataclass(frozen=True)
class RegexOutcome:
    ok: bool
    result: Any = None
    error: str | None = None


async def run_regex(
    request: dict[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    wait_seconds: float = 1.0,
) -> RegexOutcome:
    """``request`` is ``{"op": "replace" | "probe" | "match_many", ...}``; see ``regex_worker``."""
    global _active
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    while _active >= MAX_CONCURRENT_REGEX_JOBS:
        if loop.time() >= deadline:
            return RegexOutcome(ok=False, error=_BUSY)
        await asyncio.sleep(_BUSY_POLL_SECONDS)
    _active += 1
    try:
        return await _run_worker(request, timeout)
    finally:
        _active -= 1


async def _run_worker(request: dict[str, Any], timeout: float) -> RegexOutcome:
    payload = json.dumps(request).encode()  # TypeError for non-JSON input, never str()-ed
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(_WORKER),
            env={},  # the child must not see SECRET_KEY, database or Hatchet secrets
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        logger.warning("Could not start the regex worker", exc_info=True)
        return RegexOutcome(ok=False, error=_STOPPED)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(payload), timeout=timeout)
    except TimeoutError:
        return RegexOutcome(ok=False, error=_STOPPED)
    finally:
        if process.returncode is None:  # timeout, or the request was cancelled
            process.kill()
            await process.wait()
    if process.returncode != 0 or len(stdout) > MAX_RESPONSE_BYTES:
        return RegexOutcome(ok=False, error=_STOPPED)
    try:
        data = json.loads(stdout)
        if data["ok"]:
            return RegexOutcome(ok=True, result=data["result"])
        return RegexOutcome(ok=False, error=str(data["error"]))
    except (ValueError, KeyError, TypeError):
        logger.warning("The regex worker returned an unusable result")
        return RegexOutcome(ok=False, error=_STOPPED)

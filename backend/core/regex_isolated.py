"""Run a user-supplied regular expression in a killable child process (S4-07, S5 correction).

``re`` holds the GIL while it matches, so a pattern such as ``(a+)+$`` on a short input would stall
every request of the API process, not just the one that sent it. The child process has CPU and
memory limits, an empty environment, and is killed on timeout.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.isolated_process import ChildSlots, run_child

logger = logging.getLogger(__name__)

_WORKER = Path(__file__).with_name("regex_worker.py")
DEFAULT_TIMEOUT_SECONDS = 2.0
MAX_CONCURRENT_REGEX_JOBS = 4
MAX_RESPONSE_BYTES = 2_500_000

_SLOTS = ChildSlots(MAX_CONCURRENT_REGEX_JOBS)

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
    """``request`` is ``{"op": <op>, ...}`` with op one of replace, probe, match_many,
    search_lines, search_many or match_any; see ``regex_worker``."""
    async with _SLOTS.hold(wait_seconds=wait_seconds) as got:
        if not got:
            return RegexOutcome(ok=False, error=_BUSY)
        return await _run_worker(request, timeout)


async def _run_worker(request: dict[str, Any], timeout: float) -> RegexOutcome:
    payload = json.dumps(request).encode()  # TypeError for non-JSON input, never str()-ed
    stdout = await run_child(
        _WORKER, payload, timeout=timeout, max_response_bytes=MAX_RESPONSE_BYTES
    )
    if stdout is None:
        return RegexOutcome(ok=False, error=_STOPPED)
    try:
        data = json.loads(stdout)
        if data["ok"]:
            return RegexOutcome(ok=True, result=data["result"])
        return RegexOutcome(ok=False, error=str(data["error"]))
    except (ValueError, KeyError, TypeError):
        logger.warning("The regex worker returned an unusable result")
        return RegexOutcome(ok=False, error=_STOPPED)

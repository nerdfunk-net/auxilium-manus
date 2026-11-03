"""Run TextFSM in a killable child process (review finding 1, doc/AI_TOOL_CHAIN.md §43).

The device output is CLI text from a device the user chose; TextFSM matches it with ``re``, which
holds the GIL. A thread would not help (it cannot be stopped, and ``wait_for`` only stops waiting),
so the parse runs in a child with CPU and memory limits and an empty environment that is killed on
timeout, the same shape as ``core.regex_isolated``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_WORKER = Path(__file__).with_name("textfsm_worker.py")
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_CONCURRENT_JOBS = 2
MAX_RESPONSE_BYTES = 20_000_000
_BUSY_POLL_SECONDS = 0.05

# Fixed codes the worker returns per item.
NO_TEMPLATE = "no_template"
NO_MATCH = "no_match"
FAILED = "failed"
TIMEOUT = "timeout"

STOPPED = "The TextFSM parser was stopped: it used too much time or memory"
BUSY = "The TextFSM parser is busy; try again in a moment"

_active = 0


@dataclass(frozen=True)
class TextfsmItem:
    rows: list[dict[str, Any]] | None
    error: str | None


@dataclass(frozen=True)
class TextfsmOutcome:
    ok: bool
    items: tuple[TextfsmItem, ...] = ()
    error: str | None = None


async def run_textfsm(
    platform: str,
    items: Sequence[tuple[str, str]],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    wait_seconds: float = 1.0,
) -> TextfsmOutcome:
    """Parse each ``(command, output)`` with the ntc-templates of ``platform``, in a child."""
    global _active
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    while _active >= MAX_CONCURRENT_JOBS:
        if loop.time() >= deadline:
            return TextfsmOutcome(ok=False, error=BUSY)
        await asyncio.sleep(_BUSY_POLL_SECONDS)
    _active += 1
    try:
        return await _run_worker(platform, items, timeout, len(items))
    finally:
        _active -= 1


async def _run_worker(
    platform: str, items: Sequence[tuple[str, str]], timeout: float, expected: int
) -> TextfsmOutcome:
    payload = json.dumps({"platform": platform, "items": [list(item) for item in items]}).encode()
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
        logger.warning("Could not start the TextFSM worker", exc_info=True)
        return TextfsmOutcome(ok=False, error=STOPPED)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(payload), timeout=timeout)
    except TimeoutError:
        return TextfsmOutcome(ok=False, error=STOPPED)
    finally:
        if process.returncode is None:  # timeout, or the request was cancelled
            process.kill()
            await process.wait()
    if process.returncode != 0 or len(stdout) > MAX_RESPONSE_BYTES:
        return TextfsmOutcome(ok=False, error=STOPPED)
    return _decode(stdout, expected)


def _decode(stdout: bytes, expected: int) -> TextfsmOutcome:
    try:
        data = json.loads(stdout)
        answers = data["result"]
        if not data["ok"] or len(answers) != expected:
            raise ValueError("unexpected worker answer")
        items = tuple(TextfsmItem(rows=a["rows"], error=a["error"]) for a in answers)
    except ValueError, KeyError, TypeError:
        logger.warning("The TextFSM worker returned an unusable result")
        return TextfsmOutcome(ok=False, error=STOPPED)
    return TextfsmOutcome(ok=True, items=items)

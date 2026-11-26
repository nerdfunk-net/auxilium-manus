"""Run TextFSM in a killable child process (review finding 1, doc/AI_TOOL_CHAIN.md §43).

The device output is CLI text from a device the user chose; TextFSM matches it with ``re``, which
holds the GIL. A thread would not help (it cannot be stopped, and ``wait_for`` only stops waiting),
so the parse runs in a child with CPU and memory limits and an empty environment that is killed on
timeout, the same shape as ``core.regex_isolated``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.isolated_process import ChildSlots, run_child

logger = logging.getLogger(__name__)

_WORKER = Path(__file__).with_name("textfsm_worker.py")
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_CONCURRENT_JOBS = 2
MAX_RESPONSE_BYTES = 20_000_000

# Fixed codes the worker returns per item.
NO_TEMPLATE = "no_template"
NO_MATCH = "no_match"
FAILED = "failed"
TIMEOUT = "timeout"

STOPPED = "The TextFSM parser was stopped: it used too much time or memory"
BUSY = "The TextFSM parser is busy; try again in a moment"

_SLOTS = ChildSlots(MAX_CONCURRENT_JOBS)


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
    async with _SLOTS.hold(wait_seconds=wait_seconds) as got:
        if not got:
            return TextfsmOutcome(ok=False, error=BUSY)
        payload = json.dumps(
            {"platform": platform, "items": [list(item) for item in items]}
        ).encode()
        stdout = await run_child(
            _WORKER, payload, timeout=timeout, max_response_bytes=MAX_RESPONSE_BYTES
        )
    if stdout is None:
        return TextfsmOutcome(ok=False, error=STOPPED)
    return _decode(stdout, len(items))


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

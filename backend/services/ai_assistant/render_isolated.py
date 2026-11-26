"""Run the assistant's trial Jinja render in a killable child process.

A thread cannot be stopped, so a template that loops for ages would keep burning CPU (and a
worker thread shared with the DB readers) after a timeout. The child process is killed instead,
and has its own CPU and memory limits (``render_worker.py``). The model can trigger this through
``render_template`` / ``propose_template``, so it must not be able to hurt the server.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.isolated_process import ChildSlots, run_child
from services.ai_assistant.template_render import RenderOutcome

logger = logging.getLogger(__name__)

_WORKER = Path(__file__).with_name("render_worker.py")
DEFAULT_TIMEOUT_SECONDS = 5.0
# Bounds how many child processes the assistant can have at once across all users.
MAX_CONCURRENT_RENDERS = 4
MAX_RESPONSE_BYTES = 2_500_000

_SLOTS = ChildSlots(MAX_CONCURRENT_RENDERS)

_STOPPED = RenderOutcome(ok=False, error="Rendering was stopped: it used too much time or memory")
_BUSY = RenderOutcome(ok=False, error="The template renderer is busy; try again in a moment")


async def render_isolated(
    content: str,
    context: Mapping[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    strict: bool = False,
    wait_seconds: float = 0.0,
) -> RenderOutcome:
    """Same result as ``render_lenient``. Raises ``TimeoutError`` after ``timeout`` seconds (the
    child is killed first); any other failure of the child comes back as a failed outcome."""
    # The assistant's trial render fails fast; report generation passes ``wait_seconds`` because
    # its result is stored for good and must not record "busy".
    async with _SLOTS.hold(wait_seconds=wait_seconds) as got:
        if not got:
            return _BUSY
        return await _run_worker(content, context, timeout, strict)


async def _run_worker(
    content: str, context: Mapping[str, Any], timeout: float, strict: bool
) -> RenderOutcome:
    # No default=str: an object that is not JSON is an error, not silently turned into text.
    try:
        payload = json.dumps({"content": content, "context": context, "strict": strict}).encode()
    except TypeError, ValueError:
        return RenderOutcome(
            ok=False, error="The template context contains a value that is not plain data"
        )
    stdout = await run_child(
        _WORKER,
        payload,
        timeout=timeout,
        max_response_bytes=MAX_RESPONSE_BYTES,
        timeout_raises=True,
    )
    return _STOPPED if stdout is None else _parse(stdout)


def _parse(stdout: bytes) -> RenderOutcome:
    try:
        data = json.loads(stdout)
        return RenderOutcome(
            ok=bool(data["ok"]),
            output=str(data["output"]),
            error=data["error"],
            error_line=data["error_line"],
            withheld=tuple(data["withheld"]),
        )
    except ValueError, KeyError, TypeError:
        logger.warning("The template render worker returned an unusable result")
        return _STOPPED

"""Run the assistant's trial Jinja render in a killable child process.

A thread cannot be stopped, so a template that loops for ages would keep burning CPU (and a
worker thread shared with the DB readers) after a timeout. The child process is killed instead,
and has its own CPU and memory limits (``render_worker.py``). The model can trigger this through
``render_template`` / ``propose_template``, so it must not be able to hurt the server.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from services.ai_assistant.template_render import RenderOutcome

logger = logging.getLogger(__name__)

_WORKER = Path(__file__).with_name("render_worker.py")
DEFAULT_TIMEOUT_SECONDS = 5.0
# Bounds how many child processes the assistant can have at once across all users.
MAX_CONCURRENT_RENDERS = 4
MAX_RESPONSE_BYTES = 2_500_000

_active = 0

_STOPPED = RenderOutcome(ok=False, error="Rendering was stopped: it used too much time or memory")
_BUSY = RenderOutcome(ok=False, error="The template renderer is busy; try again in a moment")


async def render_isolated(
    content: str,
    context: Mapping[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> RenderOutcome:
    """Same result as ``render_lenient``. Raises ``TimeoutError`` after ``timeout`` seconds (the
    child is killed first); any other failure of the child comes back as a failed outcome."""
    global _active
    if _active >= MAX_CONCURRENT_RENDERS:
        return _BUSY
    _active += 1
    try:
        return await _run_worker(content, context, timeout)
    finally:
        _active -= 1


async def _run_worker(content: str, context: Mapping[str, Any], timeout: float) -> RenderOutcome:
    payload = json.dumps({"content": content, "context": context}, default=str).encode()
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(_WORKER),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        logger.warning("Could not start the template render worker", exc_info=True)
        return _STOPPED
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(payload), timeout=timeout)
    finally:
        if process.returncode is None:  # timeout, or the request was cancelled
            process.kill()
            await process.wait()
    return _parse(process.returncode, stdout)


def _parse(returncode: int | None, stdout: bytes) -> RenderOutcome:
    if returncode != 0 or len(stdout) > MAX_RESPONSE_BYTES:
        return _STOPPED
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

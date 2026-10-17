"""Run coroutines from synchronous pytest tests on one persistent event loop.

The project has no ``pytest-asyncio`` / ``anyio`` pytest plugin (unit tests use
``unittest.IsolatedAsyncioTestCase``). Integration tests define an
``async def _body(...)`` and call ``run(_body(...))``.

Why one shared loop and not ``asyncio.run`` per call: session-scoped services
(e.g. ``NautobotService``'s ``httpx.AsyncClient``) bind their connection pools to
the loop that first ran them. ``asyncio.run`` closes its loop on return, so the
next call would hit ``RuntimeError: Event loop is closed``. ``conftest.py`` closes
this loop once in ``pytest_unconfigure``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

_loop: asyncio.AbstractEventLoop | None = None


def get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return get_loop().run_until_complete(coro)


def close_loop() -> None:
    global _loop
    if _loop is not None and not _loop.is_closed():
        _loop.close()
    _loop = None

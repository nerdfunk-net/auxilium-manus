"""Reverse DNS for the hosts that answered, with the container's default resolver.

``socket.gethostbyaddr`` blocks and cannot be cancelled: after our deadline the thread stays busy
until the system resolver gives up (several seconds per nameserver, longer with a black-holed
one). So all lookups of the process share **one** fixed-size pool; stuck lookups can occupy its
threads but can never create more of them, however many scans run. A lookup that is still queued
when its deadline (or the phase budget) passes is cancelled before it starts. Whatever fails or is
too slow is simply "no name": DNS must never turn a successful scan into an error.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

DEFAULT_CONCURRENCY = 32
# The whole lookup phase may take this long, however many hosts answered; what is not resolved by
# then has no name. Keeps a scan inside the step timeout (the ICMP part has already been paid for).
DEFAULT_BUDGET_SECONDS = 15.0

_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()


def _shared_pool() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(
                max_workers=DEFAULT_CONCURRENCY, thread_name_prefix="manus-dns"
            )
        return _pool


def _system_lookup(ip: str) -> str:
    return socket.gethostbyaddr(ip)[0]


async def resolve_names(
    addresses: list[str],
    *,
    timeout: float,  # noqa: ASYNC109 - a per-lookup deadline, not an asyncio.timeout() scope
    budget: float = DEFAULT_BUDGET_SECONDS,
    lookup: Callable[[str], str] = _system_lookup,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> dict[str, str | None]:
    """``{address: name or None}`` for every address."""
    names: dict[str, str | None] = dict.fromkeys(addresses)
    if not addresses:
        return names
    loop = asyncio.get_running_loop()
    pool = _shared_pool()
    gate = asyncio.Semaphore(min(concurrency, DEFAULT_CONCURRENCY))

    async def one(ip: str) -> None:
        async with gate:
            future = loop.run_in_executor(pool, lookup, ip)
            try:
                done, _ = await asyncio.wait({future}, timeout=timeout)
            except asyncio.CancelledError:
                future.cancel()
                raise
            if not done:
                future.cancel()  # works only while it is still queued; a running one is left
                future.add_done_callback(_swallow)
                return
            try:
                name = future.result().strip().rstrip(".")
            except (OSError, UnicodeError, ValueError):
                return
            names[ip] = name or None

    tasks = [asyncio.ensure_future(one(ip)) for ip in addresses]
    try:
        _, pending = await asyncio.wait(tasks, timeout=budget)
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        raise
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    return names


def _swallow(future: asyncio.Future[str]) -> None:
    """Mark a late failure as retrieved; nobody is waiting for it any more."""
    if not future.cancelled():
        future.exception()

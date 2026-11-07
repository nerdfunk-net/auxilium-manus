"""Reverse DNS (PTR) lookups for the collect-client-data step.

``socket.gethostbyaddr`` has no timeout and blocks a thread, so lookups run in a small
dedicated thread pool with a per-lookup timeout, and each IP is resolved once per resolver
(the step shares one resolver across all devices of a run). Only PTR queries are sent to the
configured resolver; nothing connects to the client addresses.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from types import TracebackType

logger = logging.getLogger(__name__)

Lookup = Callable[[str], str | None]
# One run asks the resolver for at most this many distinct addresses (a table filled by ARP
# spoofing must not turn into a flood of PTR queries).
MAX_ADDRESSES = 1000


def reverse_lookup(ip: str) -> str | None:
    """PTR name of *ip*, or ``None`` when there is none."""
    try:
        return socket.gethostbyaddr(ip)[0]
    except socket.herror, socket.gaierror, OSError:
        return None


def _is_lookup_target(ip: str) -> bool:
    """False for text that is not an address and for addresses a PTR query is wasted on."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        address.is_multicast or address.is_unspecified or address.is_loopback or address.is_reserved
    )


def _clean(name: str | None, ip: str) -> str | None:
    if not name:
        return None
    cleaned = name.strip().rstrip(".")
    return cleaned if cleaned and cleaned != ip else None


class HostnameResolver:
    """Resolve IP addresses to hostnames with a timeout, a concurrency cap and a cache."""

    def __init__(
        self,
        *,
        timeout: float,
        concurrency: int,
        lookup: Lookup = reverse_lookup,
        max_addresses: int = MAX_ADDRESSES,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than 0")
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        self._timeout = timeout
        self._lookup = lookup
        self._max_addresses = max_addresses
        self._executor = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="rdns")
        self._semaphore = asyncio.Semaphore(concurrency)
        self._tasks: dict[str, asyncio.Task[str | None]] = {}

    async def __aenter__(self) -> HostnameResolver:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # A timed-out lookup may still be running in its thread; do not wait for it.
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def resolve(self, ips: Iterable[str]) -> dict[str, str]:
        """Hostnames for the IPs that have one; failures, timeouts and unusable or surplus
        addresses are left out."""
        unique = sorted({ip for ip in ips if _is_lookup_target(ip)})
        tasks = {ip: task for ip in unique if (task := self._task(ip)) is not None}
        names = await asyncio.gather(*tasks.values())
        return {ip: name for ip, name in zip(tasks, names, strict=True) if name}

    def _task(self, ip: str) -> asyncio.Task[str | None] | None:
        task = self._tasks.get(ip)
        if task is None:
            if len(self._tasks) >= self._max_addresses:
                logger.warning("reverse DNS address cap reached cap=%d", self._max_addresses)
                return None
            task = asyncio.ensure_future(self._lookup_one(ip))
            self._tasks[ip] = task
        return task

    def _release(self, future: asyncio.Future[str | None]) -> None:
        self._semaphore.release()
        if not future.cancelled():
            future.exception()  # retrieved: an abandoned lookup must not log "never retrieved"

    async def _lookup_one(self, ip: str) -> str | None:
        # The slot is taken before the lookup is submitted and given back only when its thread
        # ends, so the timeout counts from the start of the lookup (not from queueing) and an
        # abandoned lookup keeps its slot: in-flight resolver calls never exceed the limit.
        await self._semaphore.acquire()
        future = asyncio.get_running_loop().run_in_executor(self._executor, self._lookup, ip)
        future.add_done_callback(self._release)
        try:
            name = await asyncio.wait_for(asyncio.shield(future), self._timeout)
        except TimeoutError:
            logger.debug("reverse DNS lookup timed out ip=%s", ip)
            return None
        except OSError:
            logger.debug("reverse DNS lookup failed ip=%s", ip)
            return None
        return _clean(name, ip)

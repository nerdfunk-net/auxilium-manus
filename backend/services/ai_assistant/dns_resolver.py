"""The resolver behind ``get_dns_lookup``: the backend host's own DNS (doc/AI_TOOL_CHAIN.md §50).

Standard library only, so the answer is what ``getaddrinfo`` / ``gethostbyaddr`` give on the
machine that runs the backend (``/etc/hosts`` and search domains included). Nothing here raises:
every failure becomes a status, so the tool never has to guess from an exception.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol, TypeVar

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

DEFAULT_TIMEOUT_SECONDS = 3.0
# A timed-out lookup keeps its worker thread until the OS gives up. The lookups run in their own
# pool of this size, so the cap ends when the OS call ends (not when our timer does) and a
# blackholed resolver cannot fill the process default executor.
_MAX_CONCURRENT_LOOKUPS = 8
_NOT_FOUND_GAI = frozenset(
    code
    for code in (getattr(socket, "EAI_NONAME", None), getattr(socket, "EAI_NODATA", None))
    if code
)
_NOT_FOUND_HERROR = frozenset({1, 4})  # HOST_NOT_FOUND, NO_DATA
_POOL = ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_LOOKUPS, thread_name_prefix="dns-lookup")


@dataclass(frozen=True)
class DnsAnswer:
    """``status`` is ``found``, ``not_found``, ``unavailable`` or ``outside_allowed_domain``.

    The last one: the name is an alias for a name outside the allowed suffixes; ``values`` is
    empty and ``canonical_name`` says where it points.
    """

    status: str
    values: tuple[str, ...]
    canonical_name: str | None


class DnsResolver(Protocol):
    allowed_suffixes: tuple[str, ...]

    async def forward(self, name: str) -> DnsAnswer: ...

    async def reverse(self, address: str) -> DnsAnswer: ...


_UNAVAILABLE = DnsAnswer("unavailable", (), None)
_NOT_FOUND = DnsAnswer("not_found", (), None)


class SystemDnsResolver:
    def __init__(
        self, allowed_suffixes: tuple[str, ...], timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        self.allowed_suffixes = allowed_suffixes
        self._timeout = timeout_seconds

    async def forward(self, name: str) -> DnsAnswer:
        try:
            # The trailing dot makes the name absolute: no search list, no ndots expansion.
            infos = await self._bounded(
                socket.getaddrinfo,
                name.rstrip(".") + ".",
                None,
                0,
                socket.SOCK_STREAM,
                0,
                socket.AI_CANONNAME,
            )
        except socket.gaierror as exc:
            return _NOT_FOUND if exc.errno in _NOT_FOUND_GAI else _UNAVAILABLE
        except (TimeoutError, OSError) as exc:
            logger.warning("DNS forward lookup failed: %s", type(exc).__name__)
            return _UNAVAILABLE
        addresses = sorted({str(info[4][0]).split("%", 1)[0] for info in infos})
        if not addresses:
            return _NOT_FOUND
        canonical = next((str(info[3]).rstrip(".").lower() for info in infos if info[3]), None)
        if canonical and not self._in_allowed_domain(canonical):
            return DnsAnswer("outside_allowed_domain", (), canonical)
        return DnsAnswer("found", tuple(addresses), canonical)

    async def reverse(self, address: str) -> DnsAnswer:
        try:
            host, aliases, _ = await self._bounded(socket.gethostbyaddr, address)
        except socket.herror as exc:
            return _NOT_FOUND if exc.errno in _NOT_FOUND_HERROR else _UNAVAILABLE
        except socket.gaierror as exc:
            return _NOT_FOUND if exc.errno in _NOT_FOUND_GAI else _UNAVAILABLE
        except (TimeoutError, OSError) as exc:
            logger.warning("DNS reverse lookup failed: %s", type(exc).__name__)
            return _UNAVAILABLE
        # Some resolvers answer with the address itself when there is no PTR record.
        names = sorted({n.rstrip(".") for n in (host, *aliases) if n and n != address})
        return DnsAnswer("found", tuple(names), None) if names else _NOT_FOUND

    def _in_allowed_domain(self, name: str) -> bool:
        return any(name.endswith("." + suffix) for suffix in self.allowed_suffixes)

    async def _bounded(self, func: Callable[..., _T], *args: object) -> _T:
        # The timeout covers the wait for one of the pool's workers as well as the lookup.
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(loop.run_in_executor(_POOL, func, *args), self._timeout)

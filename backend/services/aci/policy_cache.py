"""Per-source cache of the fabric policy snapshot for Ask the Net.

A snapshot is about 17 APIC reads and can be large; a chat turn may need it several times. The
cache holds fabric data that is the same for anybody who may read the source, never a user's
gated view, so callers must check the permission and the data switches **before** asking it.
Concurrent callers for one key wait for one fetch (single flight). A failed fetch is not cached.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable

from services.aci.policy_service import AciPolicySnapshot

DEFAULT_TTL_SECONDS = 120.0
DEFAULT_MAX_ENTRIES = 8
# The cache holds at most this many policy objects in all (EPGs, contracts with their subjects and
# relations, L3Outs), whatever the number of entries: a few huge fabrics must not fill the process.
# A snapshot larger than the cap is returned but not kept.
DEFAULT_MAX_OBJECTS = 200_000


def weigh(snapshot: AciPolicySnapshot) -> int:
    """A rough size of a snapshot, in objects."""
    contracts = sum(
        1 + len(c.subjects) + len(c.provider_epgs) + len(c.consumer_epgs)
        for c in snapshot.contracts.values()
    )
    l3outs = sum(
        1 + len(o.nodes) + len(o.interfaces) + len(o.external_epgs)
        for o in snapshot.l3outs.values()
    )
    return len(snapshot.epgs) + contracts + l3outs


class PolicyCache:
    def __init__(
        self,
        *,
        ttl: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_objects: int = DEFAULT_MAX_OBJECTS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._max = max_entries
        self._max_objects = max_objects
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, AciPolicySnapshot]] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}

    def _fresh(self, key: str) -> tuple[AciPolicySnapshot, float] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        age = self._clock() - entry[0]
        if age >= self._ttl:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return entry[1], age

    async def get(
        self, key: str, loader: Callable[[], Awaitable[AciPolicySnapshot]]
    ) -> tuple[AciPolicySnapshot, float]:
        """The snapshot for ``key`` and its age in seconds, loading it when missing or stale."""
        if (hit := self._fresh(key)) is not None:
            return hit
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if (hit := self._fresh(key)) is not None:  # another caller loaded it while we waited
                return hit
            snapshot = await loader()
            if weigh(snapshot) > self._max_objects:
                self._entries.pop(key, None)  # too big to keep: the next caller reads it again
                return snapshot, 0.0
            self._entries[key] = (self._clock(), snapshot)
            self._trim()
            return snapshot, 0.0

    def _trim(self) -> None:
        """Drop the oldest entries until both the entry count and the object total fit."""
        while len(self._entries) > self._max or (
            len(self._entries) > 1
            and sum(weigh(s) for _, s in self._entries.values()) > self._max_objects
        ):
            evicted, _ = self._entries.popitem(last=False)
            self._locks.pop(evicted, None)

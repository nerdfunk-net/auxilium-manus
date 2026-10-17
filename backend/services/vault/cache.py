"""In-process TTL cache for resolved KV secrets.

The :class:`SecretCache` Protocol is the seam a Redis-backed shared cache slots
into later (see ``doc/VAULT_INTEGRATION.md`` — "caching"). For now only the
per-process :class:`InProcessTTLCache` exists. Only *successful* reads are ever
cached; a failed read must never populate or be served from the cache.
"""

from __future__ import annotations

import threading
import time
from typing import Protocol


class SecretCache(Protocol):
    """Path -> secret-fields mapping with expiry. Values are plain dicts."""

    def get(self, path: str) -> dict | None: ...

    def set(self, path: str, value: dict) -> None: ...

    def invalidate(self, path: str) -> None: ...

    def clear(self) -> None: ...


class InProcessTTLCache:
    """Thread-safe dict cache keyed by KV path with a fixed TTL per entry."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, dict]] = {}

    def get(self, path: str) -> dict | None:
        with self._lock:
            entry = self._store.get(path)
            if entry is None:
                return None
            expires_at, value = entry
            if time.monotonic() >= expires_at:
                del self._store[path]
                return None
            # Hand back a copy so callers cannot mutate the cached dict.
            return dict(value)

    def set(self, path: str, value: dict) -> None:
        with self._lock:
            self._store[path] = (time.monotonic() + self._ttl, dict(value))

    def invalidate(self, path: str) -> None:
        with self._lock:
            self._store.pop(path, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

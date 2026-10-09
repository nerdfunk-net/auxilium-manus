"""Lazy, per-connection ``SecretManagerClient`` cache.

Unlike ``core/vault.py``'s two-singleton pattern (exactly one OpenBao
connection, known at boot from env vars), Secret Manager connections are DB
rows discovered at first use — there is no fixed set to start eagerly. Each
connection gets its own live client instance on first use.

The cache is process-local (API + each Hatchet worker has its own). Router
``invalidate()`` only drops the API process's entry; workers notice edits,
deactivations, and deletes by re-reading ``(is_active, updated_at)`` on every
``get_or_create`` (SM4).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from services.secret_manager.client import SecretManagerClient
from services.secret_manager.config import SecretManagerConnectionConfig, load_connection_config
from services.secret_manager.connection_service import (
    SecretManagerConnectionGeneration,
    SecretManagerConnectionService,
)
from services.secret_manager.exceptions import (
    SecretManagerConfigError,
    SecretManagerUnavailableError,
)

logger = logging.getLogger(__name__)


def _build_client(cfg: SecretManagerConnectionConfig) -> SecretManagerClient:
    if cfg.backend == "openbao":
        from services.secret_manager.openbao_client import OpenBaoSecretManagerClient

        return OpenBaoSecretManagerClient(cfg)
    if cfg.backend == "infisical":
        from services.secret_manager.infisical_client import InfisicalSecretManagerClient

        return InfisicalSecretManagerClient(cfg)
    raise SecretManagerConfigError(f"Unknown secret manager backend: {cfg.backend!r}")


@dataclass(frozen=True)
class _CachedClient:
    client: SecretManagerClient
    updated_at: datetime


class SecretManagerClientRegistry:
    def __init__(self) -> None:
        self._clients: dict[int, _CachedClient] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._closed = False

    def _lock_for(self, connection_id: int) -> asyncio.Lock:
        # Created synchronously (no await), so two coroutines cannot race on it.
        lock = self._locks.get(connection_id)
        if lock is None:
            lock = self._locks[connection_id] = asyncio.Lock()
        return lock

    async def _require_generation(
        self, connection_id: int, db: Session
    ) -> SecretManagerConnectionGeneration:
        generation = SecretManagerConnectionService(db).get_generation(connection_id)
        if generation is None:
            await self.invalidate(connection_id)
            raise ValueError(f"Secret manager connection {connection_id} not found")
        if not generation.is_active:
            await self.invalidate(connection_id)
            raise ValueError(
                f"Secret manager connection '{generation.name}' is not active"
            )
        return generation

    async def get_or_create(self, connection_id: int, db: Session) -> SecretManagerClient:
        # Per-connection lock: one connection's DB read + decrypt + login must not
        # block every other connection (SM8).
        lock = self._lock_for(connection_id)
        while True:
            self._raise_if_closed()
            generation = await self._require_generation(connection_id, db)

            async with lock:
                cached = self._clients.get(connection_id)
                if cached is not None and cached.updated_at == generation.updated_at:
                    return cached.client

            # Miss or mismatch. Re-read so a stale snapshot cannot evict a
            # newer cache another coroutine inserted (D5b). Then pop only
            # against this fresh snapshot.
            generation = await self._require_generation(connection_id, db)

            stale = None
            async with lock:
                cached = self._clients.get(connection_id)
                if cached is not None and cached.updated_at == generation.updated_at:
                    return cached.client
                stale = self._clients.pop(connection_id, None)

            if stale is not None:
                await stale.client.shutdown()

            async with lock:
                cached = self._clients.get(connection_id)
                if cached is not None and cached.updated_at == generation.updated_at:
                    return cached.client
                if cached is not None:
                    # Different generation appeared while we shut down — do
                    # not overwrite it; loop and re-read.
                    continue
                cfg = load_connection_config(connection_id, db)
                client = _build_client(cfg)
                await client.ensure_started()
                if self._closed:
                    # Shutdown began while we were logging in: do not leave this client
                    # (and e.g. its token-renewal task) running behind shutdown_all.
                    await client.shutdown()
                    self._raise_if_closed()
                self._clients[connection_id] = _CachedClient(
                    client=client, updated_at=generation.updated_at
                )
                return client

    def _raise_if_closed(self) -> None:
        if self._closed:
            raise SecretManagerUnavailableError("Secret manager registry is shutting down")

    async def invalidate(self, connection_id: int) -> None:
        """Drop and shut down a connection's cached client (e.g. after it was
        edited or deleted), so the next use rebuilds it from the current row."""
        async with self._lock_for(connection_id):
            cached = self._clients.pop(connection_id, None)
        if cached is not None:
            await cached.client.shutdown()

    async def shutdown_all(self) -> None:
        # Refuse new inserts first, then wait for each connection's in-flight
        # get_or_create (which holds its lock across ensure_started) before taking
        # whatever it cached; otherwise a login finishing after the snapshot would
        # leave a running client behind.
        self._closed = True
        cached_clients: list[_CachedClient] = []
        for connection_id in list(self._locks):
            async with self._lock_for(connection_id):
                cached = self._clients.pop(connection_id, None)
                if cached is not None:
                    cached_clients.append(cached)
        self._locks.clear()
        for cached in cached_clients:
            try:
                await cached.client.shutdown()
            except Exception:
                logger.warning("Error shutting down secret manager client", exc_info=True)

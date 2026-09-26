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
from services.secret_manager.exceptions import SecretManagerConfigError

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
        self._lock = asyncio.Lock()

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
        while True:
            generation = await self._require_generation(connection_id, db)

            async with self._lock:
                cached = self._clients.get(connection_id)
                if cached is not None and cached.updated_at == generation.updated_at:
                    return cached.client

            # Miss or mismatch. Re-read so a stale snapshot cannot evict a
            # newer cache another coroutine inserted (D5b). Then pop only
            # against this fresh snapshot.
            generation = await self._require_generation(connection_id, db)

            stale = None
            async with self._lock:
                cached = self._clients.get(connection_id)
                if cached is not None and cached.updated_at == generation.updated_at:
                    return cached.client
                stale = self._clients.pop(connection_id, None)

            if stale is not None:
                await stale.client.shutdown()

            async with self._lock:
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
                self._clients[connection_id] = _CachedClient(
                    client=client, updated_at=generation.updated_at
                )
                return client

    async def invalidate(self, connection_id: int) -> None:
        """Drop and shut down a connection's cached client (e.g. after it was
        edited or deleted), so the next use rebuilds it from the current row."""
        async with self._lock:
            cached = self._clients.pop(connection_id, None)
        if cached is not None:
            await cached.client.shutdown()

    async def shutdown_all(self) -> None:
        async with self._lock:
            cached_clients = list(self._clients.values())
            self._clients.clear()
        for cached in cached_clients:
            try:
                await cached.client.shutdown()
            except Exception:
                logger.warning("Error shutting down secret manager client", exc_info=True)

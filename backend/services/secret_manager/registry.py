"""Lazy, per-connection ``SecretManagerClient`` cache.

Unlike ``core/vault.py``'s two-singleton pattern (exactly one OpenBao
connection, known at boot from env vars), Secret Manager connections are DB
rows discovered at first use — there is no fixed set to start eagerly. Each
connection gets its own live client instance on first use, cached for the
process lifetime, or until :meth:`invalidate` (called by the connection
update/delete router so an edited connection doesn't keep serving a stale
client).
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.orm import Session

from services.secret_manager.client import SecretManagerClient
from services.secret_manager.config import SecretManagerConnectionConfig, load_connection_config
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


class SecretManagerClientRegistry:
    def __init__(self) -> None:
        self._clients: dict[int, SecretManagerClient] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, connection_id: int, db: Session) -> SecretManagerClient:
        async with self._lock:
            client = self._clients.get(connection_id)
            if client is not None:
                return client
            cfg = load_connection_config(connection_id, db)
            client = _build_client(cfg)
            await client.ensure_started()
            self._clients[connection_id] = client
            return client

    async def invalidate(self, connection_id: int) -> None:
        """Drop and shut down a connection's cached client (e.g. after it was
        edited or deleted), so the next use rebuilds it from the current row."""
        async with self._lock:
            client = self._clients.pop(connection_id, None)
        if client is not None:
            await client.shutdown()

    async def shutdown_all(self) -> None:
        async with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            try:
                await client.shutdown()
            except Exception:
                logger.warning("Error shutting down secret manager client", exc_info=True)

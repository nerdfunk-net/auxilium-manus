"""``SecretManagerService`` — the facade workflow steps call.

Async because resolving a connection's live client
(``SecretManagerClientRegistry.get_or_create``) may need to perform async
startup (OpenBao's token-renewal loop). Once resolved, the per-field
read/write calls are synchronous HTTP (the adapters use ``httpx.Client``), so
they run via ``asyncio.to_thread`` to keep the worker's event loop free (SM8).
Rendered paths and field names are validated here, before any client lookup
(SM5).

No ``storage_backend``-style branching lives here — which client class to use
is decided entirely inside the registry/config layer. This facade never
imports ``OpenBaoSecretManagerClient`` or ``InfisicalSecretManagerClient``.
"""

from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session

import service_factory
from services.secret_manager.client import SecretVersionInfo
from services.secret_manager.policy import SecretGenerationPolicy, generate_secret
from services.secret_manager.validation import validate_field, validate_kv_path


class SecretManagerService:
    def __init__(self, db: Session) -> None:
        self._db = db

    async def get_field(
        self, connection_id: int, path: str, field: str, *, version: int | None = None
    ) -> str | None:
        validate_kv_path(path)
        validate_field(field)
        client = await service_factory.get_secret_manager_registry().get_or_create(
            connection_id, self._db
        )
        return await asyncio.to_thread(client.get_field, path, field, version=version)

    async def set_field(
        self, connection_id: int, path: str, field: str, value: str
    ) -> int | None:
        validate_kv_path(path)
        validate_field(field)
        client = await service_factory.get_secret_manager_registry().get_or_create(
            connection_id, self._db
        )
        return await asyncio.to_thread(client.set_field, path, field, value)

    async def generate_field(
        self,
        connection_id: int,
        path: str,
        field: str,
        policy: SecretGenerationPolicy,
    ) -> tuple[int | None, str]:
        """Generate a random value per *policy*, store it, and return
        ``(version, value)`` — this is the TACACS-rotation primitive."""
        value = generate_secret(policy)
        version = await self.set_field(connection_id, path, field, value)
        return version, value

    async def get_field_history(
        self, connection_id: int, path: str, field: str
    ) -> list[SecretVersionInfo]:
        validate_kv_path(path)
        validate_field(field)
        client = await service_factory.get_secret_manager_registry().get_or_create(
            connection_id, self._db
        )
        return await asyncio.to_thread(client.get_field_history, path, field)

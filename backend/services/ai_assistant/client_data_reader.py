"""Collected client data (where MAC and IP addresses were seen) for Ask the Net, as the user.

``DbClientDataReader`` checks ``client_data:read`` on every call (the tools are offered with the
permission alone, and a revoked grant stops them at once). It only reads: the data comes from the
``collect-client-data`` workflow step (doc/CLIENT_DATA.md).
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from core.database import SessionLocal
from services.auth.rbac_service import RBACService
from services.client_data.client_data_service import ClientDataService


class ClientDataAccessError(Exception):
    """The user may not read client data."""


class ClientDataReader(Protocol):
    async def observations(self, **filters: Any) -> tuple[list[dict[str, Any]], int]: ...

    async def history(self, **filters: Any) -> dict[str, list[dict[str, Any]]]: ...

    async def coverage(self) -> list[dict[str, Any]]: ...


class DbClientDataReader:
    def __init__(self, user_id: int) -> None:
        self._user_id = user_id

    def _service(self, db: Any) -> ClientDataService:
        if not RBACService(db).has_permission(self._user_id, "client_data", "read"):
            raise ClientDataAccessError
        return ClientDataService(db)

    def _observations(self, filters: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
        with SessionLocal() as db:
            return self._service(db).get_client_data(**filters)

    def _history(self, filters: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        with SessionLocal() as db:
            return self._service(db).get_client_history(**filters)

    def _coverage(self) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            return self._service(db).get_collections()

    async def observations(self, **filters: Any) -> tuple[list[dict[str, Any]], int]:
        return await asyncio.to_thread(self._observations, filters)

    async def history(self, **filters: Any) -> dict[str, list[dict[str, Any]]]:
        return await asyncio.to_thread(self._history, filters)

    async def coverage(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._coverage)

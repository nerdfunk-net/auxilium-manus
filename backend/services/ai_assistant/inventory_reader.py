"""Nautobot-backed ``InventoryReader`` for the inventory tools.

Runs as the calling user: ``sources.nautobot:read`` is checked, saved inventories go through
``InventoryService`` (private inventories of others are invisible) and device data comes from the
same ``NautobotSourceService`` the inventory page uses. DB work happens in a worker thread with a
short-lived session; the Nautobot calls are awaited after the session is closed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import service_factory
from core.database import SessionLocal
from dependencies import nautobot_credentials_from_source_id
from models.sources_nautobot import LogicalOperation
from services.ai_assistant.glossary_service import GlossaryService
from services.ai_assistant.tools.inventory_tools import (
    InventoryAccessError,
    InventoryNotFoundError,
    InventoryQueryError,
)
from services.auth.rbac_service import RBACService
from services.nautobot.credentials import NautobotCredentials
from services.sources.nautobot.source_service import NautobotSourceService

logger = logging.getLogger(__name__)


class DbInventoryReader:
    def __init__(self, user_id: int, username: str, source_id: str) -> None:
        self._user_id = user_id
        self._username = username
        self._source_id = source_id

    def _credentials(self, db: Any) -> NautobotCredentials:
        if not RBACService(db).has_permission(self._user_id, "sources.nautobot", "read"):
            raise InventoryAccessError
        try:
            return nautobot_credentials_from_source_id(self._source_id, db)
        except Exception as exc:  # unknown source id or unusable config
            logger.info("AI assistant: Nautobot source %r unavailable", self._source_id)
            raise InventoryAccessError from exc

    def _service(self, credentials: NautobotCredentials) -> NautobotSourceService:
        return service_factory.build_nautobot_source_service(credentials)

    async def list_inventories(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list)

    def _list(self) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            self._credentials(db)
            rows = service_factory.build_inventory_service(db).list_inventories(
                username=self._username
            )
            return [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "type": r.get("inventory_type"),
                    "scope": r.get("scope"),
                    "description": r.get("description"),
                }
                for r in rows
            ]

    def _load(self, inventory_id: int) -> tuple[NautobotCredentials, dict[str, Any]]:
        with SessionLocal() as db:
            credentials = self._credentials(db)
            try:
                inventory = service_factory.build_inventory_service(db).get_inventory(
                    inventory_id, username=self._username
                )
            except PermissionError as exc:
                raise InventoryNotFoundError from exc
            if not inventory or inventory.get("is_active") is False:
                raise InventoryNotFoundError
            return credentials, inventory

    async def resolve_inventory(self, inventory_id: int) -> dict[str, Any]:
        credentials, inventory = await asyncio.to_thread(self._load, inventory_id)
        response = await self._service(credentials).resolve_saved_inventory_devices(inventory)
        return {
            "id": inventory["id"],
            "name": inventory["name"],
            "inventory_type": inventory.get("inventory_type"),
            "devices": [d.model_dump(mode="json") for d in response.devices],
        }

    async def search_devices(self, search: str, limit: int) -> list[dict[str, Any]]:
        credentials = await asyncio.to_thread(self._only_credentials)
        devices = await self._service(credentials).search_devices_by_name(search, limit)
        return [d.model_dump(mode="json") for d in devices]

    async def get_device_attributes(
        self, device_id: str, attributes: list[str] | None
    ) -> dict[str, Any]:
        credentials = await asyncio.to_thread(self._only_credentials)
        try:
            return await self._service(credentials).get_device_attributes(device_id, attributes)
        except ValueError as exc:
            raise InventoryNotFoundError from exc

    async def field_values(self, field: str) -> list[dict[str, str]]:
        credentials = await asyncio.to_thread(self._only_credentials)
        return await self._service(credentials).get_field_values(field)

    async def preview_operations(self, operations: list[LogicalOperation]) -> list[dict[str, Any]]:
        credentials = await asyncio.to_thread(self._only_credentials)
        service = self._service(credentials)
        service.evaluator.failures.clear()
        devices, _operations_run = await service.preview_inventory(operations)
        if service.evaluator.failures:
            # The evaluator turns a failed condition into "no devices"; that is not an answer.
            raise InventoryQueryError
        return [d.model_dump(mode="json") for d in devices]

    async def glossary_lookup(self, term: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._glossary, term)

    async def glossary_suggest(self, term: str) -> list[str]:
        return await asyncio.to_thread(self._glossary_suggest, term)

    def _glossary_suggest(self, term: str) -> list[str]:
        with SessionLocal() as db:
            self._credentials(db)
            return GlossaryService(db).suggest("inventory_filter", term)

    def _glossary(self, term: str) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            self._credentials(db)  # same gate as every other inventory read
            return GlossaryService(db).lookup("inventory_filter", term)

    def _only_credentials(self) -> NautobotCredentials:
        with SessionLocal() as db:
            return self._credentials(db)

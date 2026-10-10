"""DB-backed adapters for the workflow tools: reference lists and validation as the user.

Tools run inside an async generator after the request's session was released, so each call opens
its own short-lived session in a worker thread and checks the calling user's RBAC itself.
"""

from __future__ import annotations

import asyncio
from typing import Any

from core.database import SessionLocal
from repositories.inventory_repository import InventoryRepository
from repositories.settings_repository import SettingsRepository
from services.ai_assistant.tools.workflow_tools import ReferencePermissionError
from services.auth.rbac_service import RBACService
from services.credentials.credentials_service import CredentialsService
from services.git.repository_service import GitRepositoryService
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from services.settings.source_keys import SourceType, source_key_prefix
from services.workflow.workflow_validation_service import WorkflowValidationService

SOURCE_TYPES: tuple[SourceType, ...] = (
    "nautobot",
    "ise",
    "pyats",
    "mattermost",
    "batfish",
    "catalyst_center",
)


class DbReferenceReader:
    """Lists what the user could pick in the builder: ids and names only, never secrets."""

    def __init__(self, user_id: int, username: str) -> None:
        self._user_id = user_id
        self._username = username

    async def list_references(self, kind: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list, kind)

    def _list(self, kind: str) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            rbac = RBACService(db)

            def require(resource: str) -> None:
                if not rbac.has_permission(self._user_id, resource, "read"):
                    raise ReferencePermissionError

            if kind == "credentials":
                require("credentials")
                rows = CredentialsService(db).list_credentials(
                    include_expired=False, source="general", acting_user_id=self._user_id
                )
                return [{"id": r["id"], "name": r["name"], "type": r["type"]} for r in rows]
            if kind == "git_repositories":
                require("git.repositories")
                rows = GitRepositoryService(db).get_repositories(active_only=True)
                return [
                    {"id": r["id"], "name": r["name"], "category": r.get("category")} for r in rows
                ]
            if kind == "inventories":
                require("sources.nautobot")
                inventories = InventoryRepository(db).list_inventories(username=self._username)
                return [
                    {"id": i.id, "name": i.name, "scope": i.scope, "type": i.inventory_type}
                    for i in inventories
                ]
            if kind == "sources":
                settings_repo = SettingsRepository(db)
                found: list[dict[str, Any]] = []
                for source_type in SOURCE_TYPES:
                    if not rbac.has_permission(self._user_id, f"sources.{source_type}", "read"):
                        continue
                    prefix = source_key_prefix(source_type)
                    found.extend(
                        {"type": source_type, "id": row.key.removeprefix(prefix)}
                        for row in settings_repo.list_all(key_prefix=prefix)
                    )
                return found
            return []


class DbWorkflowValidator:
    """Runs the four validation tiers as the calling user (credential visibility is per user)."""

    def __init__(self, user_id: int, registry: PluginRegistryService) -> None:
        self._user_id = user_id
        self._registry = registry

    async def validate(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> Any:
        return await asyncio.to_thread(self._run, nodes, edges)

    def _run(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> Any:
        with SessionLocal() as db:
            return WorkflowValidationService(db, self._registry).validate(
                nodes, edges, acting_user_id=self._user_id
            )

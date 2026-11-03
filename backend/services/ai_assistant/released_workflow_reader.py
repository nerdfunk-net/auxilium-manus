"""DB-backed access to the workflows released for Ask the Net (doc/AI_TOOL_CHAIN.md §16).

Everything runs as the calling user: the workflow must be released, visible to them, and they need
``workflows:execute`` (and ``workflows:read`` to see the catalogue). Each call opens its own
short-lived session in a worker thread, like ``DbRunReader``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from core.database import SessionLocal
from core.models.workflows import Workflow
from repositories.workflow_repository import WorkflowRepository
from services.ai_assistant.device_access import DbDeviceResolver
from services.auth.rbac_service import RBACService
from services.execution.run_service import RunService


class ReleasedWorkflowAccessError(Exception):
    """Not released, not visible or not allowed: deliberately one message."""

    def __init__(self) -> None:
        super().__init__("That workflow is not released for you")


@dataclass(frozen=True)
class ReleasedWorkflow:
    id: int
    name: str
    description: str
    result_node_id: str | None
    static_attributes: tuple[dict[str, Any], ...]


class ReleasedWorkflowReader(Protocol):
    async def list_released(self) -> list[ReleasedWorkflow]: ...

    async def get_released(self, workflow_id: int) -> ReleasedWorkflow: ...

    async def resolve_devices(self, names: list[str]) -> list[tuple[str, str]]: ...

    async def start(
        self, workflow_id: int, *, run_inputs: dict[str, Any], device_ids: list[str]
    ) -> int: ...


def _to_released(workflow: Workflow) -> ReleasedWorkflow:
    return ReleasedWorkflow(
        id=workflow.id,
        name=workflow.name,
        description=workflow.ai_description or "",
        result_node_id=workflow.ai_result_node_id,
        static_attributes=tuple(workflow.static_attributes or ()),
    )


def _visible(workflow: Workflow, user_id: int) -> bool:
    return bool(workflow.ai_released) and (
        workflow.visibility != "private" or workflow.creator_id == user_id
    )


class DbReleasedWorkflowReader:
    def __init__(self, user_id: int) -> None:
        self._user_id = user_id

    async def list_released(self) -> list[ReleasedWorkflow]:
        return await asyncio.to_thread(self._list_released)

    async def get_released(self, workflow_id: int) -> ReleasedWorkflow:
        return await asyncio.to_thread(self._get_released, workflow_id)

    async def resolve_devices(self, names: list[str]) -> list[tuple[str, str]]:
        """``(device_id, name)`` per name; raises ``DeviceAccessError`` (a safe message)."""
        resolver = DbDeviceResolver(self._user_id)
        found = [await resolver.resolve_without_address(name) for name in names]
        return [(d.device_id, d.name) for d in found]

    async def start(
        self, workflow_id: int, *, run_inputs: dict[str, Any], device_ids: list[str]
    ) -> int:
        return await asyncio.to_thread(self._start, workflow_id, run_inputs, device_ids)

    def _require_execute(self, db: Any) -> None:
        if not RBACService(db).has_permission(self._user_id, "workflows", "execute"):
            raise ReleasedWorkflowAccessError

    def _list_released(self) -> list[ReleasedWorkflow]:
        with SessionLocal() as db:
            self._require_execute(db)
            rows = WorkflowRepository(db).list_accessible(self._user_id)
            return [_to_released(w) for w, _ in rows if _visible(w, self._user_id)]

    def _get_released(self, workflow_id: int) -> ReleasedWorkflow:
        with SessionLocal() as db:
            self._require_execute(db)
            found = WorkflowRepository(db).get_by_id(workflow_id)
            if found is None or not _visible(found[0], self._user_id):
                raise ReleasedWorkflowAccessError
            return _to_released(found[0])

    def _start(self, workflow_id: int, run_inputs: dict[str, Any], device_ids: list[str]) -> int:
        with SessionLocal() as db:
            self._require_execute(db)
            run = RunService(db).trigger_ai_run(
                workflow_id, self._user_id, run_inputs=run_inputs, device_ids=device_ids
            )
            return run.id

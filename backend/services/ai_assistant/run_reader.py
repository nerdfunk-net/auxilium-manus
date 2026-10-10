"""DB-backed ``RunReader`` for the run-viewer tools.

Delegates to ``RunService`` so run visibility (private workflows) is enforced exactly as for the
REST endpoints; adds the RBAC checks the routers do with ``require_permission``. Each call opens
its own short-lived session in a worker thread (tools run after the request session is released).
"""

from __future__ import annotations

import asyncio
from typing import Any

from core.database import SessionLocal
from core.domain_exceptions import AccessDeniedError, NotFoundError
from repositories.workflow_repository import WorkflowRepository
from services.ai_assistant.tools.run_tools import RunAccessError
from services.auth.rbac_service import RBACService
from services.execution.run_service import RunService

EVENT_FETCH_LIMIT = 1000  # the service's own page maximum


class DbRunReader:
    def __init__(self, user_id: int) -> None:
        self._user_id = user_id

    async def get_run(self, run_id: int) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_run, run_id)

    async def list_events(
        self, run_id: int, limit: int, node_id: str | None
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_events, run_id, limit, node_id)

    async def get_artifact(self, run_id: int, artifact_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_artifact, run_id, artifact_id)

    async def get_workflow(self, run_id: int) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_workflow, run_id)

    def _require_runs(self, db: Any) -> None:
        if not RBACService(db).has_permission(self._user_id, "workflow_runs", "read"):
            raise RunAccessError

    def _get_run(self, run_id: int) -> dict[str, Any]:
        with SessionLocal() as db:
            self._require_runs(db)
            try:
                return RunService(db).get_run(run_id, self._user_id).model_dump(mode="json")
            except (NotFoundError, AccessDeniedError) as exc:
                raise RunAccessError from exc

    def _list_events(self, run_id: int, limit: int, node_id: str | None) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            self._require_runs(db)
            try:
                page = RunService(db).list_events(run_id, self._user_id, limit=EVENT_FETCH_LIMIT)
            except (NotFoundError, AccessDeniedError) as exc:
                raise RunAccessError from exc
            rows = [e.model_dump(mode="json") for e in page.events]
            # Filter before slicing so a later step's events are not lost behind earlier ones.
            return [r for r in rows if node_id is None or r["step_node_id"] == node_id][:limit]

    def _get_artifact(self, run_id: int, artifact_id: str) -> dict[str, Any] | None:
        with SessionLocal() as db:
            self._require_runs(db)
            service = RunService(db)
            try:
                service.get_run(run_id, self._user_id)  # run visibility first
            except (NotFoundError, AccessDeniedError) as exc:
                raise RunAccessError from exc
            try:
                return service.get_run_artifact(run_id, artifact_id, self._user_id).model_dump(
                    mode="json"
                )
            except NotFoundError:
                return None

    def _get_workflow(self, run_id: int) -> dict[str, Any] | None:
        with SessionLocal() as db:
            self._require_runs(db)
            try:
                run = RunService(db).get_run(run_id, self._user_id)
            except (NotFoundError, AccessDeniedError) as exc:
                raise RunAccessError from exc
            if not RBACService(db).has_permission(self._user_id, "workflows", "read"):
                return None
            found = WorkflowRepository(db).get_by_id(run.workflow_id)
            if found is None:
                return None
            workflow, _creator = found
            return {
                "name": workflow.name,
                "canvas_nodes": workflow.canvas_nodes or [],
                "canvas_edges": workflow.canvas_edges or [],
                "static_attributes": workflow.static_attributes or [],
            }

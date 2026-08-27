from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from core.domain_exceptions import (
    AccessDeniedError,
    DomainError,
    NotFoundError,
    ValidationFailedError,
)
from core.models.workflows import Workflow
from models.workflows import (
    StaticAttributeDef,
    WorkflowCreate,
    WorkflowListResponse,
    WorkflowNameCheckResponse,
    WorkflowResponse,
    WorkflowSummary,
    WorkflowUpdate,
)
from repositories.workflow_repository import WorkflowRepository
from services.execution.background_tier_service import BackgroundTierService
from services.execution.graph import GraphCycleError, topological_order
from services.execution.schedule_service import ScheduleService

logger = logging.getLogger(__name__)


def _validate_no_cycle(canvas_nodes: list[dict], canvas_edges: list[dict]) -> None:
    """Raise HTTP 400 if the canvas graph contains a cycle.

    See doc/FABLE-ANALYSIS.md §4.2: without this, a cyclic graph is accepted
    at save time and then silently loses the cyclic nodes at run time (they
    never reach in-degree 0 in StepRunner's topological sort).
    """
    try:
        topological_order(canvas_nodes, canvas_edges)
    except GraphCycleError as exc:
        raise ValidationFailedError(str(exc)) from exc


def _validate_static_attributes(static_attributes: list[dict] | list[StaticAttributeDef]) -> None:
    """Raise HTTP 400 on a duplicate attribute name or a default value that
    doesn't match its declared type — the same shape checks a hand-typed
    canvas config field never gets, but this schema drives a generated form
    (the run-inputs dialog), so a bad row there breaks every future run."""
    seen: set[str] = set()
    for raw in static_attributes:
        attr = (
            raw
            if isinstance(raw, StaticAttributeDef)
            else StaticAttributeDef.model_validate(raw)
        )
        if attr.name in seen:
            raise ValidationFailedError(f"Duplicate static attribute name: {attr.name!r}")
        seen.add(attr.name)
        if attr.default is None:
            continue
        is_number = isinstance(attr.default, (int, float)) and not isinstance(attr.default, bool)
        type_ok = (
            (attr.type == "string" and isinstance(attr.default, str))
            or (attr.type == "number" and is_number)
            or (attr.type == "boolean" and isinstance(attr.default, bool))
        )
        if not type_ok:
            raise ValidationFailedError(
                f"Static attribute {attr.name!r}: default does not match type {attr.type!r}"
            )


def _to_summary(workflow: Workflow, creator_username: str | None) -> WorkflowSummary:
    return WorkflowSummary(
        id=workflow.id,
        uuid=workflow.uuid,
        name=workflow.name,
        creator_id=workflow.creator_id,
        creator_username=creator_username,
        description=workflow.description,
        folder=workflow.folder,
        visibility=workflow.visibility,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def _to_response(workflow: Workflow, creator_username: str | None) -> WorkflowResponse:
    return WorkflowResponse(
        id=workflow.id,
        uuid=workflow.uuid,
        name=workflow.name,
        creator_id=workflow.creator_id,
        creator_username=creator_username,
        description=workflow.description,
        folder=workflow.folder,
        visibility=workflow.visibility,
        canvas_nodes=workflow.canvas_nodes,
        canvas_edges=workflow.canvas_edges,
        canvas_groups=workflow.canvas_groups,
        static_attributes=workflow.static_attributes,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


class WorkflowService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = WorkflowRepository(db)

    def list_workflows(self, user_id: int) -> WorkflowListResponse:
        logger.debug("Listing accessible workflows user_id=%s", user_id)
        rows = self.repo.list_accessible(user_id)
        summaries = [_to_summary(wf, username) for wf, username in rows]
        logger.debug("Listed accessible workflows user_id=%s total=%s", user_id, len(summaries))
        return WorkflowListResponse(workflows=summaries, total=len(summaries))

    def get_workflow(self, workflow_id: int, user_id: int) -> WorkflowResponse:
        logger.debug("Getting workflow id=%s user_id=%s", workflow_id, user_id)
        result = self.repo.get_by_id(workflow_id)
        if result is None:
            raise NotFoundError("Workflow not found")
        workflow, creator_username = result
        if workflow.visibility == "private" and workflow.creator_id != user_id:
            raise AccessDeniedError("Access denied")
        return _to_response(workflow, creator_username)

    def create_workflow(self, data: WorkflowCreate, user_id: int) -> WorkflowResponse:
        logger.info("Creating workflow name=%r user_id=%s", data.name, user_id)
        _validate_no_cycle(data.canvas_nodes, data.canvas_edges)
        _validate_static_attributes(data.static_attributes)
        try:
            workflow = self.repo.create(
                name=data.name,
                creator_id=user_id,
                description=data.description,
                folder=data.folder,
                visibility=data.visibility,
                canvas_nodes=data.canvas_nodes,
                canvas_edges=data.canvas_edges,
                canvas_groups=data.canvas_groups,
                static_attributes=[attr.model_dump() for attr in data.static_attributes],
            )
            result = self.repo.get_by_id(workflow.id)
            if result is None:
                logger.error(
                    "Workflow created but could not be retrieved id=%s user_id=%s",
                    workflow.id,
                    user_id,
                )
                raise RuntimeError("Workflow created but could not be retrieved")
            wf, creator_username = result
            logger.info("Workflow created id=%s name=%r user_id=%s", wf.id, wf.name, user_id)
            return _to_response(wf, creator_username)
        except DomainError:
            raise
        except Exception:
            logger.info(
                "Failed to create workflow name=%r user_id=%s", data.name, user_id, exc_info=True
            )
            raise

    def update_workflow(
        self, workflow_id: int, data: WorkflowUpdate, user_id: int
    ) -> WorkflowResponse:
        logger.info("Updating workflow id=%s user_id=%s", workflow_id, user_id)
        try:
            result = self.repo.get_by_id(workflow_id)
            if result is None:
                raise NotFoundError("Workflow not found")
            workflow, creator_username = result
            if workflow.creator_id != user_id:
                raise AccessDeniedError("Access denied")
            updated_fields = data.model_dump(exclude_unset=True)
            if "canvas_nodes" in updated_fields or "canvas_edges" in updated_fields:
                _validate_no_cycle(
                    updated_fields.get("canvas_nodes", workflow.canvas_nodes),
                    updated_fields.get("canvas_edges", workflow.canvas_edges),
                )
            if "static_attributes" in updated_fields:
                _validate_static_attributes(updated_fields["static_attributes"] or [])
            workflow = self.repo.update(workflow, updated_fields)
            logger.info("Workflow updated id=%s user_id=%s", workflow_id, user_id)
            return _to_response(workflow, creator_username)
        except DomainError:
            raise
        except Exception:
            logger.info(
                "Failed to update workflow id=%s user_id=%s", workflow_id, user_id, exc_info=True
            )
            raise

    def check_name_available(
        self,
        *,
        name: str,
        folder: str,
        visibility: str,
        user_id: int,
        exclude_id: int | None = None,
    ) -> WorkflowNameCheckResponse:
        existing_id = self.repo.find_id_by_name(
            name=name,
            folder=folder or "/",
            visibility=visibility,
            creator_id=user_id,
        )
        if existing_id is None or existing_id == exclude_id:
            return WorkflowNameCheckResponse(available=True)
        if visibility == "public":
            msg = f'A public workflow named "{name}" already exists in folder "{folder or "/"}".'
        else:
            msg = f'You already have a private workflow named "{name}" in folder "{folder or "/"}".'
        return WorkflowNameCheckResponse(available=False, message=msg, existing_id=existing_id)

    def delete_workflow(self, workflow_id: int, user_id: int) -> None:
        result = self.repo.get_by_id(workflow_id)
        if result is None:
            raise NotFoundError("Workflow not found")
        workflow, _ = result
        if workflow.creator_id != user_id:
            raise AccessDeniedError("Access denied")
        ScheduleService(self.db).delete_schedule_for_workflow_unchecked(workflow_id)
        BackgroundTierService(self.db).unpublish_for_workflow_unchecked(workflow_id)
        self.repo.delete(workflow)

"""Business logic for change requests — the CI/CD pipeline review gate.

A stage run's ``open-change-request`` step calls :meth:`create_from_step`. A
reviewer then advances the change request:

* :meth:`approve` — ``staged`` → ``deploying`` + dispatch a deploy run (UI
  "Approve & Deploy", or a signed webhook when the repo has
  ``webhook_auto_deploy``).
* :meth:`mark_reviewed` — ``staged`` → ``approved`` (a signed webhook when the
  repo does *not* auto-deploy). A UI "Deploy" click then calls :meth:`deploy`.
* :meth:`deploy` — ``approved`` → ``deploying`` + dispatch a deploy run.
* :meth:`reject` — ``staged`` / ``approved`` → ``rejected``.

Every state move is an atomic conditional UPDATE
(:meth:`ChangeRequestRepository.transition`) so a UI click racing a webhook
resolves to exactly one deploy run. See ``doc/CICD_PIPELINE.md``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.domain_exceptions import AccessDeniedError, ConflictError, NotFoundError
from core.models.change_requests import ChangeRequest
from core.models.workflows import Workflow
from models.artifacts import ArtifactContentResponse
from models.change_requests import (
    ChangeRequestListResponse,
    ChangeRequestResponse,
    ChangeRequestSummary,
)
from repositories.change_request_repository import ChangeRequestRepository
from repositories.run_repository import RunRepository
from repositories.workflow_repository import WorkflowRepository
from services.execution.run_service import RunService

logger = logging.getLogger(__name__)

# WorkflowRun statuses that let reconcile() finalise a deploying change request.
_DEPLOY_SUCCESS = "success"
_DEPLOY_FAILURE = frozenset({"failed", "cancelled"})


def _utcnow() -> datetime:
    return datetime.now(UTC)


def maybe_reconcile_deploy_run(db: Session, run: object) -> None:
    """Flip a change request to deployed/failed the moment its deploy run
    reaches a terminal status. Cheap no-op for every non-deploy run (guarded by
    ``run.change_request_id``); safe to call from the Hatchet worker's own
    session. Never raises — a reconcile failure must not fail the run.
    """
    change_request_id = getattr(run, "change_request_id", None)
    if not change_request_id:
        return
    try:
        repo = ChangeRequestRepository(db)
        change_request = repo.get_by_id(int(change_request_id))
        if change_request is not None:
            ChangeRequestService(db).reconcile(change_request)
    except Exception:  # noqa: BLE001 — best-effort; logged, never propagated
        logger.warning(
            "Failed to reconcile change request for run change_request_id=%s",
            change_request_id,
            exc_info=True,
        )


class ChangeRequestService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ChangeRequestRepository(db)
        self.wf_repo = WorkflowRepository(db)
        self.run_repo = RunRepository(db)

    # ── helpers ─────────────────────────────────────────────────────────────

    def _get_or_404(self, change_request_id: int) -> ChangeRequest:
        change_request = self.repo.get_by_id(change_request_id)
        if change_request is None:
            raise NotFoundError("Change request not found")
        return change_request

    def _assert_visible(self, change_request: ChangeRequest, user_id: int) -> None:
        if change_request.source_workflow_id is None:
            return
        wf_result = self.wf_repo.get_by_id(change_request.source_workflow_id)
        if wf_result is None:
            return
        workflow, _ = wf_result
        if workflow.visibility == "private" and workflow.creator_id != user_id:
            raise AccessDeniedError("Access denied")

    def _load_workflow(self, workflow_id: int) -> Workflow:
        wf_result = self.wf_repo.get_by_id(workflow_id)
        if wf_result is None:
            raise NotFoundError("Deploy workflow not found")
        workflow, _ = wf_result
        return workflow

    def _to_response(self, change_request: ChangeRequest) -> ChangeRequestResponse:
        return ChangeRequestResponse.model_validate(
            {
                **{
                    c.name: getattr(change_request, c.name)
                    for c in change_request.__table__.columns
                },
                "approved_by_username": self.repo.approved_by_username(change_request),
            }
        )

    # ── create (called by the open-change-request step) ─────────────────────

    def create_from_step(
        self,
        *,
        source_workflow_id: int | None,
        source_run_id: int | None,
        deploy_workflow_id: int | None,
        git_repository_id: int | None,
        base_branch: str | None,
        branch: str | None,
        commit_sha: str | None,
        title: str | None,
        device_ids: list[str],
        run_inputs: dict,
        diff_artifact_id: str | None,
        diff_stats: dict | None,
        expires_after_hours: int,
    ) -> ChangeRequest:
        expires_at = (
            _utcnow() + timedelta(hours=expires_after_hours)
            if expires_after_hours and expires_after_hours > 0
            else None
        )
        try:
            change_request = self.repo.create(
                source_workflow_id=source_workflow_id,
                source_run_id=source_run_id,
                deploy_workflow_id=deploy_workflow_id,
                git_repository_id=git_repository_id,
                base_branch=base_branch,
                branch=branch,
                commit_sha=commit_sha,
                title=title,
                device_ids=device_ids,
                run_inputs=run_inputs,
                diff_artifact_id=diff_artifact_id,
                diff_stats=diff_stats,
                expires_at=expires_at,
            )
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError(
                "An active change request already exists for this repository and commit"
            ) from exc
        logger.info(
            "Created change_request id=%s branch=%s commit=%s source_run=%s",
            change_request.id,
            branch,
            (commit_sha or "")[:8],
            source_run_id,
        )
        return change_request

    # ── reads ──────────────────────────────────────────────────────────────

    def list(self, user_id: int, *, statuses: list[str] | None = None) -> ChangeRequestListResponse:
        rows = self.repo.list_visible(user_id, statuses=statuses)
        items = [ChangeRequestSummary.model_validate(row) for row in rows]
        return ChangeRequestListResponse(items=items, total=len(items))

    def get(self, change_request_id: int, user_id: int) -> ChangeRequestResponse:
        change_request = self._get_or_404(change_request_id)
        self._assert_visible(change_request, user_id)
        change_request = self.reconcile(change_request)
        return self._to_response(change_request)

    def get_diff(self, change_request_id: int, user_id: int) -> ArtifactContentResponse:
        change_request = self._get_or_404(change_request_id)
        self._assert_visible(change_request, user_id)
        if change_request.diff_artifact_id is None or change_request.source_run_id is None:
            raise NotFoundError("This change request has no stored diff")
        return RunService(self.db).get_run_artifact(
            change_request.source_run_id, change_request.diff_artifact_id, user_id
        )

    # ── transitions ────────────────────────────────────────────────────────

    def approve(
        self,
        change_request_id: int,
        *,
        actor_user_id: int | None,
        via: str,
        deploy_workflow_id: int | None = None,
    ) -> ChangeRequestResponse:
        change_request = self._get_or_404(change_request_id)
        target_workflow_id = deploy_workflow_id or change_request.deploy_workflow_id
        if target_workflow_id is None:
            raise ConflictError(
                "No deploy workflow is set for this change request; "
                "provide deploy_workflow_id"
            )
        workflow = self._load_workflow(target_workflow_id)

        moved = self.repo.transition(
            change_request,
            expected_statuses={"staged"},
            new_status="deploying",
            approved_by_id=actor_user_id,
            approved_via=via,
            approved_at=_utcnow(),
            deploy_workflow_id=target_workflow_id,
        )
        if moved is None:
            raise ConflictError(
                f"Change request is not awaiting approval (status={change_request.status})"
            )
        return self._dispatch_deploy(moved, workflow, actor_user_id=actor_user_id, via=via)

    def mark_reviewed(
        self, change_request_id: int, *, via: str = "webhook"
    ) -> ChangeRequestResponse:
        change_request = self._get_or_404(change_request_id)
        moved = self.repo.transition(
            change_request,
            expected_statuses={"staged"},
            new_status="approved",
            approved_via=via,
            approved_at=_utcnow(),
        )
        if moved is None:
            raise ConflictError(
                f"Change request is not awaiting approval (status={change_request.status})"
            )
        logger.info("Change request id=%s marked reviewed via=%s", change_request_id, via)
        return self._to_response(moved)

    def deploy(
        self,
        change_request_id: int,
        *,
        actor_user_id: int | None,
        deploy_workflow_id: int | None = None,
    ) -> ChangeRequestResponse:
        change_request = self._get_or_404(change_request_id)
        target_workflow_id = deploy_workflow_id or change_request.deploy_workflow_id
        if target_workflow_id is None:
            raise ConflictError(
                "No deploy workflow is set for this change request; "
                "provide deploy_workflow_id"
            )
        workflow = self._load_workflow(target_workflow_id)

        moved = self.repo.transition(
            change_request,
            expected_statuses={"approved"},
            new_status="deploying",
            deploy_workflow_id=target_workflow_id,
        )
        if moved is None:
            raise ConflictError(
                f"Change request is not in 'approved' state (status={change_request.status})"
            )
        return self._dispatch_deploy(
            moved, workflow, actor_user_id=actor_user_id, via="ui"
        )

    def reject(
        self, change_request_id: int, *, actor_user_id: int | None, reason: str | None
    ) -> ChangeRequestResponse:
        change_request = self._get_or_404(change_request_id)
        moved = self.repo.transition(
            change_request,
            expected_statuses={"staged", "approved"},
            new_status="rejected",
            rejected_by_id=actor_user_id,
            rejected_at=_utcnow(),
            reject_reason=reason,
        )
        if moved is None:
            raise ConflictError(
                f"Change request cannot be rejected from status={change_request.status}"
            )
        logger.info("Change request id=%s rejected", change_request_id)
        return self._to_response(moved)

    # ── deploy dispatch + reconciliation ──────────────────────────────────

    def _dispatch_deploy(
        self,
        change_request: ChangeRequest,
        workflow: Workflow,
        *,
        actor_user_id: int | None,
        via: str,
    ) -> ChangeRequestResponse:
        trigger_type = "webhook" if via == "webhook" else "manual"
        try:
            run = RunService(self.db)._create_and_dispatch_run(
                workflow,
                triggered_by_id=actor_user_id,
                trigger_type=trigger_type,
                device_ids=list(change_request.device_ids or []),
                run_inputs=dict(change_request.run_inputs or {}),
                change_request_id=change_request.id,
            )
        except Exception:
            self.repo.transition(
                change_request,
                expected_statuses={"deploying"},
                new_status="failed",
                deploy_error="Failed to dispatch the deploy run",
            )
            raise
        # We won the transition to "deploying", so we hold it exclusively —
        # a plain field update is safe here.
        change_request.deploy_run_id = run.id
        self.db.commit()
        self.db.refresh(change_request)
        logger.info(
            "Change request id=%s dispatched deploy run_id=%s workflow_id=%s via=%s",
            change_request.id,
            run.id,
            workflow.id,
            via,
        )
        return self._to_response(change_request)

    def reconcile(self, change_request: ChangeRequest) -> ChangeRequest:
        """Finalise a ``deploying`` change request once its deploy run reaches a
        terminal status. Idempotent; a no-op for every other status.
        """
        if change_request.status != "deploying" or change_request.deploy_run_id is None:
            return change_request
        run_result = self.run_repo.get_run_by_id(change_request.deploy_run_id)
        if run_result is None:
            return change_request
        run, _ = run_result
        if run.status == _DEPLOY_SUCCESS:
            moved = self.repo.transition(
                change_request, expected_statuses={"deploying"}, new_status="deployed"
            )
            return moved or change_request
        if run.status in _DEPLOY_FAILURE:
            moved = self.repo.transition(
                change_request,
                expected_statuses={"deploying"},
                new_status="failed",
                deploy_error=run.error_message or f"Deploy run {run.status}",
            )
            return moved or change_request
        return change_request

    def reconcile_all_in_flight(self) -> int:
        changed = 0
        for change_request in self.repo.list_in_flight():
            before = change_request.status
            after = self.reconcile(change_request).status
            if after != before:
                changed += 1
        return changed

    def expire_sweep(self) -> int:
        expired = 0
        for change_request in self.repo.list_expired_candidates(now=_utcnow()):
            moved = self.repo.transition(
                change_request, expected_statuses={"staged"}, new_status="expired"
            )
            if moved is not None:
                expired += 1
        return expired

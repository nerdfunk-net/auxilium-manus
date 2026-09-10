from __future__ import annotations

import uuid as uuid_mod
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from core.models.change_requests import ChangeRequest
from core.models.users import User
from core.models.workflows import Workflow

# Statuses that still count as "in flight" for the partial unique index and for
# webhook correlation.
_ACTIVE_STATUSES = ("staged", "approved", "deploying")


class ChangeRequestRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, change_request_id: int) -> ChangeRequest | None:
        return self.db.get(ChangeRequest, change_request_id)

    def get_by_uuid(self, change_request_uuid: str) -> ChangeRequest | None:
        stmt = select(ChangeRequest).where(ChangeRequest.uuid == change_request_uuid)
        return self.db.execute(stmt).scalar_one_or_none()

    def approved_by_username(self, change_request: ChangeRequest) -> str | None:
        if change_request.approved_by_id is None:
            return None
        return self.db.scalar(
            select(User.username).where(User.id == change_request.approved_by_id)
        )

    def create(
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
        run_inputs: dict[str, Any],
        diff_artifact_id: str | None,
        diff_stats: dict[str, Any] | None,
        expires_at: datetime | None,
    ) -> ChangeRequest:
        change_request = ChangeRequest(
            uuid=str(uuid_mod.uuid4()),
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
            status="staged",
            expires_at=expires_at,
        )
        self.db.add(change_request)
        self.db.commit()
        self.db.refresh(change_request)
        return change_request

    def list_visible(
        self, user_id: int, *, statuses: list[str] | None = None
    ) -> list[ChangeRequest]:
        """Every change request whose source workflow the user may see (public,
        or their own private), newest first."""
        stmt = (
            select(ChangeRequest)
            .outerjoin(Workflow, ChangeRequest.source_workflow_id == Workflow.id)
            .where(
                or_(
                    ChangeRequest.source_workflow_id.is_(None),
                    Workflow.visibility == "public",
                    Workflow.creator_id == user_id,
                )
            )
            .order_by(ChangeRequest.created_at.desc(), ChangeRequest.id.desc())
        )
        if statuses:
            stmt = stmt.where(ChangeRequest.status.in_(statuses))
        return list(self.db.execute(stmt).scalars())

    def find_active_for_commit(
        self, git_repository_id: int, commit_sha: str
    ) -> ChangeRequest | None:
        stmt = (
            select(ChangeRequest)
            .where(
                ChangeRequest.git_repository_id == git_repository_id,
                ChangeRequest.commit_sha == commit_sha,
                ChangeRequest.status.in_(_ACTIVE_STATUSES),
            )
            .order_by(ChangeRequest.id.desc())
        )
        return self.db.execute(stmt).scalars().first()

    def list_in_flight(self) -> list[ChangeRequest]:
        stmt = select(ChangeRequest).where(
            ChangeRequest.status.in_(("approved", "deploying"))
        )
        return list(self.db.execute(stmt).scalars())

    def list_expired_candidates(self, *, now: datetime) -> list[ChangeRequest]:
        stmt = select(ChangeRequest).where(
            ChangeRequest.status == "staged",
            ChangeRequest.expires_at.is_not(None),
            ChangeRequest.expires_at < now,
        )
        return list(self.db.execute(stmt).scalars())

    def transition(
        self,
        change_request: ChangeRequest,
        *,
        expected_statuses: set[str],
        new_status: str,
        **fields: Any,
    ) -> ChangeRequest | None:
        """Atomically move ``change_request`` to ``new_status`` iff its current
        status is one of ``expected_statuses``. Returns the refreshed row on
        success, ``None`` if the guard did not match (a concurrent approve /
        webhook won the race). No SQL string composition — Core ``update()``.
        """
        stmt = (
            update(ChangeRequest)
            .where(
                ChangeRequest.id == change_request.id,
                ChangeRequest.status.in_(tuple(expected_statuses)),
            )
            .values(status=new_status, **fields)
        )
        result = self.db.execute(stmt)
        self.db.commit()
        if (result.rowcount or 0) != 1:
            return None
        self.db.refresh(change_request)
        return change_request

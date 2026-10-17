"""Authorization for the ai-assistant's write paths.

``WorkflowService.update_workflow_for_ai_session`` / ``update_notes_for_ai_session`` skip the
owner check because the owner's time-boxed consent row (``workflow_ai_sessions``) *is* the
authorization. That consent is verified here, inside the service, so no caller can reach the
bypass without it. See doc/ai_collaboration/PROCESS.md.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.domain_exceptions import AccessDeniedError, ConflictError
from core.models.users import User
from core.models.workflow_ai_session import WorkflowAiSession
from repositories.background_tier_repository import BackgroundTierRepository
from repositories.change_request_repository import ChangeRequestRepository
from repositories.schedule_repository import ScheduleRepository
from repositories.user_repository import UserRepository
from repositories.workflow_ai_session_repository import WorkflowAiSessionRepository
from services.auth.rbac_seed import AI_ASSISTANT_USERNAME


class AiWriteGate:
    def __init__(self, db: Session) -> None:
        self._users = UserRepository(db)
        self._sessions = WorkflowAiSessionRepository(db)
        self._schedules = ScheduleRepository(db)
        self._tiers = BackgroundTierRepository(db)
        self._change_requests = ChangeRequestRepository(db)

    def require_active_ai_user(self, ai_user_id: int) -> User:
        """The caller must be the seeded ai-assistant account, and an admin must have enabled it."""
        user = self._users.get_by_id(ai_user_id)
        if user is None or user.username != AI_ASSISTANT_USERNAME:
            raise AccessDeniedError("Only the ai-assistant account may use the AI write path")
        if not user.is_active:
            raise AccessDeniedError(
                f"'{AI_ASSISTANT_USERNAME}' is disabled — an admin must activate it in "
                "Settings -> Users first"
            )
        return user

    def assert_may_write(
        self, workflow_id: int, ai_user_id: int, *, canvas: bool
    ) -> WorkflowAiSession:
        """Raise unless the AI may write *workflow_id* right now.

        ``canvas=True`` additionally refuses when the workflow has an unattended trigger (an
        enabled schedule, the background tier, an open change request's deploy workflow): each
        executes the live canvas unattended, so an AI edit would run without anybody
        having looked at it. Notes never execute and are exempt.
        """
        self.require_active_ai_user(ai_user_id)
        session = self._sessions.get_active_for_workflow(workflow_id)
        if session is None:
            raise AccessDeniedError(
                f"No active AI-updates session for workflow {workflow_id} — the owner must "
                "enable it from the canvas toolbar first"
            )
        if canvas:
            blockers = self.unattended_triggers(workflow_id)
            if blockers:
                raise ConflictError(
                    f"Workflow {workflow_id} has unattended triggers ({'; '.join(blockers)}); "
                    "remove them before an AI edit — they would run the AI's canvas unattended"
                )
        return session

    def unattended_triggers(self, workflow_id: int) -> list[str]:
        """Ways the live canvas could run without anybody looking at it (S5-07)."""
        found: list[str] = []
        enabled = sum(1 for s in self._schedules.list_by_workflow_id(workflow_id) if s.enabled)
        if enabled:
            found.append(f"{enabled} enabled schedule(s)")
        if self._tiers.get_by_workflow_id(workflow_id) is not None:
            found.append("published to the background tier")
        if self._change_requests.exists_open_deploy(workflow_id):
            found.append("deploy workflow of an open change request")
        return found

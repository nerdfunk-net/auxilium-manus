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
from repositories.schedule_repository import ScheduleRepository
from repositories.user_repository import UserRepository
from repositories.workflow_ai_session_repository import WorkflowAiSessionRepository
from services.auth.rbac_seed import AI_ASSISTANT_USERNAME


class AiWriteGate:
    def __init__(self, db: Session) -> None:
        self._users = UserRepository(db)
        self._sessions = WorkflowAiSessionRepository(db)
        self._schedules = ScheduleRepository(db)

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

        ``canvas=True`` additionally refuses when the workflow has an enabled schedule: a
        schedule executes the live canvas unattended, so an AI edit would run without anybody
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
            enabled = [s for s in self._schedules.list_by_workflow_id(workflow_id) if s.enabled]
            if enabled:
                raise ConflictError(
                    f"Workflow {workflow_id} has {len(enabled)} enabled schedule(s); disable "
                    "them before an AI edit — a schedule would run the AI's canvas unattended"
                )
        return session

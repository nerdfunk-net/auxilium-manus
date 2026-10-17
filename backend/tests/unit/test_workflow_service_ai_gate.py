"""WorkflowService.update_workflow_for_ai_session enforces the AI consent gate itself.

Modeled on tests/unit/test_workflow_service_notes.py's WorkflowService(MagicMock())
+ mocked-repo pattern.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from core.domain_exceptions import AccessDeniedError, ConflictError
from core.models.workflows import Workflow
from models.workflows import WorkflowUpdate
from services.workflow.ai_write_gate import AiWriteGate
from services.workflow.workflow_git_service import WorkflowGitSyncResult
from services.workflow.workflow_service import WorkflowService


def _persisted_workflow(**overrides) -> Workflow:
    workflow = Workflow(
        id=1,
        uuid="11111111-1111-1111-1111-111111111111",
        name="Test Workflow",
        creator_id=1,
        description=None,
        folder="/",
        visibility="private",
        canvas_nodes=[],
        canvas_edges=[],
        canvas_groups=[],
        static_attributes=[],
        notes=None,
        is_version_controlled=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    for key, value in overrides.items():
        setattr(workflow, key, value)
    return workflow


def _apply_update(workflow: Workflow, fields: dict) -> Workflow:
    for key, value in fields.items():
        setattr(workflow, key, value)
    return workflow


def _service(workflow: Workflow) -> WorkflowService:
    service = WorkflowService(MagicMock())
    service.repo = MagicMock()
    service.repo.get_by_id.return_value = (workflow, "creator")
    service.repo.update.side_effect = _apply_update
    service.git = MagicMock()
    service.git.sync_workflow_to_git.return_value = WorkflowGitSyncResult(
        status="skipped", message="not version controlled"
    )
    service.changes = MagicMock()
    service.ai_gate = MagicMock(spec=AiWriteGate)
    return service


def test_calls_gate_with_canvas_true() -> None:
    service = _service(_persisted_workflow())

    service.update_workflow_for_ai_session(
        1, WorkflowUpdate(name="Renamed"), ai_user_id=42, actor_username="ai-assistant"
    )

    service.ai_gate.assert_may_write.assert_called_once_with(1, 42, canvas=True)


@pytest.mark.parametrize("error", [AccessDeniedError("no session"), ConflictError("scheduled")])
def test_denied_gate_writes_nothing(error: Exception) -> None:
    service = _service(_persisted_workflow())
    service.ai_gate.assert_may_write.side_effect = error

    with pytest.raises(type(error)):
        service.update_workflow_for_ai_session(
            1, WorkflowUpdate(name="Renamed"), ai_user_id=42, actor_username="ai-assistant"
        )

    service.repo.update.assert_not_called()
    service.git.sync_workflow_to_git.assert_not_called()


def test_bypasses_ownership_when_gate_passes() -> None:
    workflow = _persisted_workflow(creator_id=1)
    service = _service(workflow)

    response = service.update_workflow_for_ai_session(
        1, WorkflowUpdate(name="Renamed"), ai_user_id=42, actor_username="ai-assistant"
    )

    assert response.name == "Renamed"

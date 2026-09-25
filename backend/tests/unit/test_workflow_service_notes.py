"""WorkflowService.update_notes / update_notes_for_ai_session.

Modeled on tests/unit/test_workflow_service_git_sync.py's
WorkflowService(MagicMock()) + mocked-repo pattern. Covers the same
ownership-check-vs-AI-session-bypass shape update_workflow_for_ai_session
already has (see doc/ai_collaboration/PROCESS.md), applied to the separate
notes/Wiki save path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from core.domain_exceptions import AccessDeniedError, NotFoundError
from core.models.workflows import Workflow
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


def _service_with_mocked_repo(workflow: Workflow) -> WorkflowService:
    service = WorkflowService(MagicMock())
    service.repo = MagicMock()
    service.repo.get_by_id.return_value = (workflow, "creator")
    service.repo.update.side_effect = _apply_update
    return service


def test_update_notes_updates_the_field_for_the_owner() -> None:
    workflow = _persisted_workflow(creator_id=1)
    service = _service_with_mocked_repo(workflow)

    response = service.update_notes(1, user_id=1, notes="# Purpose\nBacks up devices.")

    assert response.notes == "# Purpose\nBacks up devices."


def test_update_notes_rejects_a_non_owner() -> None:
    workflow = _persisted_workflow(creator_id=1)
    service = _service_with_mocked_repo(workflow)

    with pytest.raises(AccessDeniedError):
        service.update_notes(1, user_id=999, notes="hijacked")


def test_update_notes_for_ai_session_bypasses_ownership() -> None:
    # ai-assistant is never the creator of a workflow the human made -- the
    # same reason update_workflow_for_ai_session exists for the canvas path.
    workflow = _persisted_workflow(creator_id=1)
    service = _service_with_mocked_repo(workflow)

    response = service.update_notes_for_ai_session(
        1, notes="## Gotchas\nRemoves all other users.", ai_user_id=42
    )

    assert response.notes == "## Gotchas\nRemoves all other users."


def test_update_notes_for_ai_session_can_clear_with_none() -> None:
    workflow = _persisted_workflow(creator_id=1, notes="stale content")
    service = _service_with_mocked_repo(workflow)

    response = service.update_notes_for_ai_session(1, notes=None, ai_user_id=42)

    assert response.notes is None


def test_update_notes_for_ai_session_raises_not_found_for_missing_workflow() -> None:
    service = WorkflowService(MagicMock())
    service.repo = MagicMock()
    service.repo.get_by_id.return_value = None

    with pytest.raises(NotFoundError):
        service.update_notes_for_ai_session(999, notes="x", ai_user_id=42)

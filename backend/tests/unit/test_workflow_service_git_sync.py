"""WorkflowService <-> WorkflowGitService composition contract.

Modeled on tests/unit/test_workflow_service_graph_validation.py's
WorkflowService(MagicMock()) pattern. Proves the DB save always succeeds
regardless of git outcome, that git_sync rides along on the response, and
that restore enforces ownership/version-controlled checks before touching git.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from core.domain_exceptions import AccessDeniedError, ValidationFailedError
from core.models.workflows import Workflow
from models.workflows import WorkflowCreate, WorkflowUpdate
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
    service.repo.create.return_value = workflow
    service.repo.update.side_effect = _apply_update
    return service


def test_update_workflow_succeeds_even_when_git_sync_fails() -> None:
    workflow = _persisted_workflow(is_version_controlled=True)
    service = _service_with_mocked_repo(workflow)
    service.git = MagicMock()
    service.git.sync_workflow_to_git.return_value = WorkflowGitSyncResult(
        status="failed", message="network blip"
    )

    response = service.update_workflow(1, WorkflowUpdate(name="Renamed"), user_id=1)

    assert response.name == "Renamed"
    assert response.git_sync is not None
    assert response.git_sync.status == "failed"
    assert response.git_sync.message == "network blip"


def test_create_workflow_attaches_ok_git_sync_status() -> None:
    workflow = _persisted_workflow()
    service = _service_with_mocked_repo(workflow)
    service.git = MagicMock()
    service.git.sync_workflow_to_git.return_value = WorkflowGitSyncResult(
        status="ok", commit_sha="abc123", pushed=True
    )

    response = service.create_workflow(WorkflowCreate(name="Test Workflow"), user_id=1)

    assert response.git_sync is not None
    assert response.git_sync.status == "ok"
    assert response.git_sync.commit_sha == "abc123"


def test_restore_workflow_version_rejects_when_not_version_controlled() -> None:
    workflow = _persisted_workflow(is_version_controlled=False)
    service = _service_with_mocked_repo(workflow)
    service.git = MagicMock()

    with pytest.raises(ValidationFailedError):
        service.restore_workflow_version(1, "deadbeef", user_id=1)

    service.git.restore_version.assert_not_called()


def test_restore_workflow_version_enforces_ownership_before_git_call() -> None:
    workflow = _persisted_workflow(creator_id=1, is_version_controlled=True)
    service = _service_with_mocked_repo(workflow)
    service.git = MagicMock()

    with pytest.raises(AccessDeniedError):
        service.restore_workflow_version(1, "deadbeef", user_id=999)

    service.git.restore_version.assert_not_called()


def test_restore_workflow_version_applies_historical_content_via_update() -> None:
    workflow = _persisted_workflow(creator_id=1, is_version_controlled=True)
    service = _service_with_mocked_repo(workflow)
    service.git = MagicMock()
    service.git.restore_version.return_value = WorkflowUpdate(name="Restored Name")
    service.git.sync_workflow_to_git.return_value = WorkflowGitSyncResult(status="ok")

    response = service.restore_workflow_version(1, "deadbeef", user_id=1)

    service.git.restore_version.assert_called_once_with(workflow, "deadbeef")
    assert response.name == "Restored Name"


def test_workflow_service_init_does_not_touch_the_database() -> None:
    with patch("service_factory.build_git_service", return_value=MagicMock()):
        service = WorkflowService(MagicMock())
    assert service.git is not None

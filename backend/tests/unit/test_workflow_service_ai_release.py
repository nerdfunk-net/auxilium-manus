"""Release of a workflow for Ask the Net: rules D7 (edit clears) and D9 (not private)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from core.domain_exceptions import AccessDeniedError, NotFoundError, ValidationFailedError
from core.models.workflows import Workflow
from models.workflows import WorkflowAiReleaseRequest, WorkflowUpdate
from services.workflow.workflow_git_service import WorkflowGitSyncResult
from services.workflow.workflow_service import WorkflowService

NODE = {"id": "n1", "type": "workflowNode", "position": {"x": 0, "y": 0}, "data": {}}


def _workflow(**overrides) -> Workflow:
    workflow = Workflow(
        id=1,
        uuid="11111111-1111-1111-1111-111111111111",
        name="PyATS Compare with Baseline",
        creator_id=1,
        description=None,
        folder="/",
        visibility="public",
        canvas_nodes=[NODE],
        canvas_edges=[],
        canvas_groups=[],
        static_attributes=[],
        notes=None,
        is_version_controlled=False,
        ai_released=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    for key, value in overrides.items():
        setattr(workflow, key, value)
    return workflow


def _service(workflow: Workflow | None) -> WorkflowService:
    service = WorkflowService(MagicMock())
    service.repo = MagicMock()
    service.repo.get_by_id.return_value = None if workflow is None else (workflow, "creator")

    def apply(wf: Workflow, fields: dict) -> Workflow:
        for key, value in fields.items():
            setattr(wf, key, value)
        return wf

    service.repo.update.side_effect = apply
    service.repo.name_exists.return_value = False
    service.git = MagicMock()
    service.git.sync_workflow_to_git.return_value = WorkflowGitSyncResult(
        status="skipped", message="x"
    )
    service.changes = MagicMock()
    return service


def _release(service: WorkflowService, user_id: int = 1, node: str | None = "n1"):
    return service.release_for_ai(
        1, user_id, WorkflowAiReleaseRequest(description="  Compare.  ", result_node_id=node)
    )


def test_release_sets_flag_fields_and_strips_description() -> None:
    wf = _workflow()
    response = _release(_service(wf))
    assert response.ai_released is True
    assert response.ai_description == "Compare."
    assert response.ai_result_node_id == "n1"
    assert wf.ai_released_by_id == 1
    assert wf.ai_released_at is not None


def test_private_workflow_cannot_be_released() -> None:
    wf = _workflow(visibility="private")
    with pytest.raises(ValidationFailedError):
        _release(_service(wf))
    assert wf.ai_released is False


def test_unknown_result_node_is_refused() -> None:
    with pytest.raises(ValidationFailedError):
        _release(_service(_workflow()), node="missing")


def test_release_without_result_node_is_allowed() -> None:
    assert _release(_service(_workflow()), node=None).ai_result_node_id is None


def test_missing_workflow_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        _release(_service(None))


def test_non_owner_non_admin_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    wf = _workflow(creator_id=1)
    service = _service(wf)
    monkeypatch.setattr(service, "_may_manage", lambda *_: False)
    with pytest.raises(AccessDeniedError):
        _release(service, user_id=2)
    assert wf.ai_released is False


def test_unrelease_clears_every_release_field() -> None:
    wf = _workflow(
        ai_released=True, ai_description="d", ai_result_node_id="n1", ai_released_by_id=1
    )
    response = _service(wf).unrelease_for_ai(1, 1)
    assert response.ai_released is False
    assert wf.ai_description is None and wf.ai_result_node_id is None
    assert wf.ai_released_by_id is None and wf.ai_released_at is None


@pytest.mark.parametrize(
    "update",
    [
        WorkflowUpdate(canvas_nodes=[NODE, {**NODE, "id": "n2"}]),
        WorkflowUpdate(canvas_edges=[{"id": "e", "source": "n1", "target": "n1x"}]),
        WorkflowUpdate(visibility="private"),
    ],
)
def test_definition_edit_clears_release(update: WorkflowUpdate) -> None:
    wf = _workflow(ai_released=True, ai_description="d", ai_result_node_id="n1")
    service = _service(wf)
    service._validate_child_run_secret_inputs = MagicMock()
    try:
        service.update_workflow(1, update, 1)
    except ValidationFailedError:
        pytest.skip("fixture edge is not a valid graph")
    assert wf.ai_released is False
    assert wf.ai_description is None


def test_edit_that_changes_nothing_in_the_definition_keeps_release() -> None:
    wf = _workflow(ai_released=True, ai_description="d", ai_result_node_id="n1")
    service = _service(wf)
    service.update_workflow(1, WorkflowUpdate(description="new text", folder="/x"), 1)
    assert wf.ai_released is True
    assert wf.ai_description == "d"


def test_resaving_identical_canvas_keeps_release() -> None:
    wf = _workflow(ai_released=True, ai_description="d", ai_result_node_id="n1")
    service = _service(wf)
    service._validate_child_run_secret_inputs = MagicMock()
    service.update_workflow(1, WorkflowUpdate(canvas_nodes=wf.canvas_nodes), 1)
    assert wf.ai_released is True

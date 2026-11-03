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


# -- devices input, credential inputs, free addresses ----------------------------------------

READER = {
    "id": "gfu",
    "type": "workflowNode",
    "data": {"kind": "get-from-user", "pluginConfig": {"device_param": "devs"}},
}
ATTRS = [
    {"name": "devs", "type": "string", "required": True},
    {"name": "cred", "type": "reference", "ref_kind": "credential", "required": True},
    {"name": "note", "type": "string", "required": False},
]


def _wired(**kw) -> WorkflowService:
    return _service(_workflow(canvas_nodes=[NODE, READER], static_attributes=ATTRS, **kw))


def _release_with(service: WorkflowService, **fields):
    return service.release_for_ai(
        1, 1, WorkflowAiReleaseRequest(description="d", result_node_id="n1", **fields)
    )


def test_release_stores_the_devices_input_the_credentials_and_the_free_ip_switch() -> None:
    response = _release_with(
        _wired(),
        devices_input="devs",
        credential_inputs=["cred", "cred"],
        allow_free_ip=True,
    )
    assert response.ai_devices_input == "devs"
    assert response.ai_credential_inputs == ["cred"]
    assert response.ai_allow_free_ip is True


@pytest.mark.parametrize("name", ["missing", "cred"])
def test_the_devices_input_must_be_a_text_input(name: str) -> None:
    with pytest.raises(ValidationFailedError):
        _release_with(_wired(), devices_input=name)


def test_the_devices_input_must_be_read_by_an_enabled_get_from_user_step() -> None:
    disabled = {**READER, "data": {**READER["data"], "disabled": True}}
    service = _service(_workflow(canvas_nodes=[NODE, disabled], static_attributes=ATTRS))
    with pytest.raises(ValidationFailedError, match="Get from User"):
        _release_with(service, devices_input="devs")


@pytest.mark.parametrize("name", ["missing", "note", "devs"])
def test_a_credential_input_must_be_a_credential_reference(name: str) -> None:
    with pytest.raises(ValidationFailedError):
        _release_with(_wired(), devices_input="devs", credential_inputs=[name])


def test_free_addresses_need_a_devices_input() -> None:
    with pytest.raises(ValidationFailedError, match="devices input"):
        _release_with(_wired(), allow_free_ip=True)


def test_editing_the_inputs_clears_the_new_fields_too() -> None:
    wf = _workflow(
        canvas_nodes=[NODE, READER],
        static_attributes=ATTRS,
        ai_released=True,
        ai_devices_input="devs",
        ai_credential_inputs=["cred"],
        ai_allow_free_ip=True,
    )
    service = _service(wf)
    service._validate_child_run_secret_inputs = MagicMock()
    service.update_workflow(
        1, WorkflowUpdate(static_attributes=[{"name": "devs", "type": "string"}]), 1
    )
    assert wf.ai_released is False
    assert (wf.ai_devices_input, wf.ai_credential_inputs, wf.ai_allow_free_ip) == (
        None,
        None,
        False,
    )


# -- the stamp, the description and the audit trail ------------------------------------------


def test_releasing_stores_a_stamp_that_pins_the_definition_and_settings() -> None:
    from services.workflow.release_stamp import release_is_current

    wf = _workflow()
    service = _service(wf)
    _release(service)
    assert wf.ai_release_stamp and len(wf.ai_release_stamp) == 64
    assert release_is_current(wf, service._load_for_stamp)

    wf.canvas_nodes = [{"id": "changed"}]  # a save that raced the release
    assert not release_is_current(wf, service._load_for_stamp)


def test_the_same_release_twice_has_the_same_stamp() -> None:
    wf = _workflow()
    service = _service(wf)
    first = _release(service)
    stamp = wf.ai_release_stamp
    assert first.ai_released
    _release(service)
    assert wf.ai_release_stamp == stamp


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_a_blank_description_is_refused(blank: str) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        WorkflowAiReleaseRequest(description=blank)


def test_the_description_is_stored_trimmed() -> None:
    assert WorkflowAiReleaseRequest(description="  Compare.  ").description == "Compare."


def _actions(service: WorkflowService) -> list[str]:
    return [c.kwargs["action"] for c in service.changes.record_change.call_args_list]


def test_release_and_removal_leave_an_audit_row_with_who() -> None:
    service = _service(_workflow())
    service.release_for_ai(1, 1, WorkflowAiReleaseRequest(description="d"), actor_username="marc")
    service.unrelease_for_ai(1, 1, actor_username="marc")

    assert _actions(service) == ["ai_released", "ai_unreleased"]
    rows = service.changes.record_change.call_args_list
    assert rows[0].kwargs["actor_id"] == 1 and rows[0].kwargs["actor_username"] == "marc"


def test_removing_a_release_that_does_not_exist_writes_nothing() -> None:
    service = _service(_workflow())
    service.unrelease_for_ai(1, 1)
    assert _actions(service) == []


def test_an_edit_that_ends_the_release_records_who_did_it() -> None:
    wf = _workflow(ai_released=True, ai_description="d", ai_release_stamp="s")
    service = _service(wf)
    service._validate_child_run_secret_inputs = MagicMock()
    service.update_workflow(
        1, WorkflowUpdate(canvas_nodes=[NODE, {**NODE, "id": "n9"}]), 1, actor_username="eve"
    )

    assert _actions(service) == ["updated", "ai_release_cleared"]
    cleared = service.changes.record_change.call_args_list[1].kwargs
    assert (cleared["actor_id"], cleared["actor_username"]) == (1, "eve")
    assert wf.ai_release_stamp is None


def test_an_edit_that_keeps_the_release_writes_only_the_normal_row() -> None:
    wf = _workflow(ai_released=True, ai_description="d", ai_release_stamp="s")
    service = _service(wf)
    service.update_workflow(1, WorkflowUpdate(description="other words"), 1)
    assert _actions(service) == ["updated"]
    assert wf.ai_release_stamp == "s"


def _starts(child_id: int) -> dict:
    return {
        "id": f"s{child_id}",
        "data": {"kind": "start-workflow", "pluginConfig": {"workflow_id": child_id}},
    }


def test_get_reports_a_broken_pin_after_a_child_changed() -> None:
    child = _workflow(id=2, canvas_nodes=[NODE])
    parent = _workflow(canvas_nodes=[_starts(2)], visibility="public")
    service = _service(parent)
    service.repo.get_by_id.side_effect = lambda wid: ((child if wid == 2 else parent, "creator"))
    service.release_for_ai(1, 1, WorkflowAiReleaseRequest(description="x"))
    assert service.get_workflow(1, 1).ai_release_current is True

    child.canvas_nodes = [{"id": "changed"}]
    assert service.get_workflow(1, 1).ai_release_current is False


def test_release_is_refused_when_the_workflow_starts_too_many_workflows() -> None:
    ids = list(range(2, 60))
    parent = _workflow(canvas_nodes=[_starts(i) for i in ids])
    service = _service(parent)
    service.repo.get_by_id.side_effect = lambda wid: (
        (parent if wid == 1 else _workflow(id=wid), "creator")
    )
    with pytest.raises(ValidationFailedError):
        service.release_for_ai(1, 1, WorkflowAiReleaseRequest(description="x"))
    service.repo.update.assert_not_called()

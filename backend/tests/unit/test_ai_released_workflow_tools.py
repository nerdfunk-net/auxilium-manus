"""Released-workflow tools: refusal rules, proposal contents, result gating."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.device_access import DeviceNotFoundError
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.released_workflow_reader import (
    ReleasedWorkflow,
    ReleasedWorkflowAccessError,
)
from services.ai_assistant.tools.base import Toolbox, ToolContext
from services.ai_assistant.tools.released_workflow_tools import (
    RELEASED_WORKFLOWS_KEY,
    build_released_workflow_tools,
)
from services.ai_assistant.tools.run_tools import RunAccessError, run_viewer_extras
from services.ai_assistant.workflow_run_token import verify_run_token

ATTRS = (
    {"name": "features", "type": "string", "required": True},
    {"name": "token", "type": "secret", "required": False},
)
WORKFLOW = ReleasedWorkflow(
    id=5,
    name="PyATS Compare",
    description="Compare.",
    result_node_id="cmp",
    static_attributes=ATTRS,
)
STEP = {
    "step_node_id": "cmp",
    "step_type": "compare-pyats-snapshot",
    "step_name": "Compare",
    "status": "success",
    "output": {
        "outcomes": {
            "mismatch": {
                "devices": {
                    "d1": {
                        "id": "d1",
                        "name": "sw1",
                        "status": "ok",
                        "parsed": {"cmp.comparison_diff": {"ospf": "- a\n+ b"}},
                    }
                }
            }
        }
    },
}


class FakeReleased:
    def __init__(self, workflow: ReleasedWorkflow | None = WORKFLOW) -> None:
        self.workflow = workflow

    async def list_released(self):
        return [self.workflow] if self.workflow else []

    async def get_released(self, workflow_id):
        if self.workflow is None or workflow_id != self.workflow.id:
            raise ReleasedWorkflowAccessError
        return self.workflow

    async def resolve_devices(self, names):
        if "ghost" in names:
            raise DeviceNotFoundError
        return [(f"id-{n}", n) for n in names]


class FakeRuns:
    def __init__(self, status: str = "success", denied: bool = False) -> None:
        self.status, self.denied = status, denied

    async def get_run(self, run_id):
        if self.denied:
            raise RunAccessError
        return {"id": run_id, "workflow_id": 5, "status": self.status, "step_results": [STEP]}


def _box(*, content: bool = True, released=None, runs=None) -> Toolbox:
    sharing = SharingPolicy(inventory=content, content=content)
    extras: dict[str, Any] = {RELEASED_WORKFLOWS_KEY: released or FakeReleased()}
    extras.update(run_viewer_extras(runs or FakeRuns(), sharing, can_list_runs=True))
    ctx = ToolContext(user_id=9, redactor=Redactor(), extras=extras, sharing=sharing)
    return Toolbox(build_released_workflow_tools(), ctx)


def _call(box: Toolbox, name: str, **input_: Any):
    return asyncio.run(box.execute(ToolCall("1", name, input_)))


def test_list_and_describe_hide_user_only_inputs() -> None:
    assert "PyATS Compare" in _call(_box(), "list_released_workflows").content
    described = json.loads(_call(_box(), "describe_workflow", workflow_id=5).content)
    token = next(i for i in described["inputs"] if i["name"] == "token")
    assert token["set_by"].startswith("the user")


def test_describe_unreleased_is_refused() -> None:
    out = _call(_box(released=FakeReleased(None)), "describe_workflow", workflow_id=5)
    assert out.is_error


def test_propose_builds_a_verifiable_proposal() -> None:
    out = _call(
        _box(), "propose_workflow_run", workflow_id=5, inputs={"features": "ospf"}, devices=["sw1"]
    )
    assert not out.is_error and out.proposal is not None
    assert out.proposal["kind"] == "workflow_run"
    assert out.proposal["devices"] == [{"id": "id-sw1", "name": "sw1"}]
    grant = verify_run_token(out.proposal["token"], user_id=9)
    assert (grant.workflow_id, grant.run_inputs, grant.device_ids) == (
        5,
        {"features": "ospf"},
        ("id-sw1",),
    )
    assert "NOT started" in out.content


def test_propose_refuses_a_secret_input_from_the_model() -> None:
    out = _call(
        _box(), "propose_workflow_run", workflow_id=5, inputs={"features": "x", "token": "t"}
    )
    assert out.is_error and out.proposal is None


def test_propose_refuses_when_a_required_secret_only_the_user_can_give() -> None:
    attrs = ({"name": "pw", "type": "secret", "required": True},)
    wf = ReleasedWorkflow(5, "W", "d", None, attrs)
    out = _call(_box(released=FakeReleased(wf)), "propose_workflow_run", workflow_id=5)
    assert out.is_error and "workflow page" in out.content


def test_propose_reports_invalid_inputs_and_unknown_devices() -> None:
    missing = _call(_box(), "propose_workflow_run", workflow_id=5)
    unknown = _call(_box(), "propose_workflow_run", workflow_id=5, inputs={"nope": 1})
    ghost = _call(
        _box(), "propose_workflow_run", workflow_id=5, inputs={"features": "a"}, devices=["ghost"]
    )
    assert missing.is_error and unknown.is_error and ghost.is_error
    assert all(o.proposal is None for o in (missing, unknown, ghost))


def test_propose_rejects_too_many_devices_and_unknown_fields() -> None:
    assert _call(_box(), "propose_workflow_run", workflow_id=5, devices=["d"] * 21).is_error
    assert _call(_box(), "propose_workflow_run", workflow_id=5, host="1.2.3.4").is_error


def test_result_reads_only_the_designated_node_with_content_opt_in() -> None:
    out = _call(_box(), "get_run_result", run_id=1)
    assert not out.is_error and "ospf" in out.content and "+ b" in out.content


def test_result_withholds_content_without_opt_in() -> None:
    out = _call(_box(content=False), "get_run_result", run_id=1)
    assert "+ b" not in out.content and "content_data" in out.content


def test_result_waits_for_a_finished_run() -> None:
    out = _call(_box(runs=FakeRuns("running")), "get_run_result", run_id=1)
    assert "running" in out.content and "ospf" not in out.content


def test_result_needs_a_designated_node_and_a_release() -> None:
    no_node = ReleasedWorkflow(5, "W", "d", None, ())
    assert (
        "no result step"
        in _call(_box(released=FakeReleased(no_node)), "get_run_result", run_id=1).content
    )
    assert _call(_box(released=FakeReleased(None)), "get_run_result", run_id=1).is_error
    assert _call(_box(runs=FakeRuns(denied=True)), "get_run_result", run_id=1).is_error


@pytest.mark.parametrize("name", ["list_released_workflows", "describe_workflow", "get_run_result"])
def test_read_tools_are_registered(name: str) -> None:
    assert name in {t.name for t in build_released_workflow_tools()}

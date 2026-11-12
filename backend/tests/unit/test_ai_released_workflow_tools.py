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
from services.ai_assistant.released_run_builder import ProposedDevice
from services.ai_assistant.released_workflow_reader import (
    FreeAddressError,
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
    {"name": "devs", "type": "string", "required": True},
    {"name": "cred", "type": "reference", "ref_kind": "credential", "required": True},
)
WORKFLOW = ReleasedWorkflow(
    id=5,
    name="PyATS Compare",
    description="Compare.",
    result_node_id="cmp",
    static_attributes=ATTRS,
    devices_input="devs",
    credential_inputs=("cred",),
    release_stamp="stamp-1",
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

    async def resolve_devices(self, refs, *, allow_free_ip):
        if "ghost" in refs:
            raise DeviceNotFoundError
        found = []
        for ref in refs:
            if ref[0].isdigit():
                if not allow_free_ip:
                    raise FreeAddressError("This workflow only accepts devices from the inventory.")
                found.append(ProposedDevice(ip=ref, in_inventory=False))
            else:
                found.append(ProposedDevice(ip="10.0.0.1", name=ref))
        return found


class FakeRuns:
    def __init__(
        self,
        status: str = "success",
        denied: bool = False,
        trigger: str = "ai_assistant",
        node: str | None = "cmp",
    ) -> None:
        self.status, self.denied, self.trigger, self.node = status, denied, trigger, node

    async def get_run(self, run_id):
        if self.denied:
            raise RunAccessError
        return {
            "id": run_id,
            "workflow_id": 5,
            "status": self.status,
            "trigger_type": self.trigger,
            "ai_result_node_id": self.node,
            "step_results": [STEP],
        }


def _box(*, content: bool = True, released=None, runs=None) -> Toolbox:
    sharing = SharingPolicy(inventory=content, content=content)
    extras: dict[str, Any] = {RELEASED_WORKFLOWS_KEY: released or FakeReleased()}
    extras.update(run_viewer_extras(runs or FakeRuns(), sharing, can_list_runs=True))
    ctx = ToolContext(user_id=9, redactor=Redactor(), extras=extras, sharing=sharing)
    return Toolbox(build_released_workflow_tools(), ctx)


def _call(box: Toolbox, name: str, **input_: Any):
    return asyncio.run(box.execute(ToolCall("1", name, input_)))


def _free_ip_workflow() -> ReleasedWorkflow:
    return ReleasedWorkflow(
        5, "Onboard", "d", None, ATTRS, devices_input="devs",
        credential_inputs=("cred",), allow_free_ip=True,
    )  # fmt: skip


def test_describe_shows_only_what_the_model_may_set() -> None:
    assert "PyATS Compare" in _call(_box(), "list_released_workflows").content
    described = json.loads(_call(_box(), "describe_workflow", workflow_id=5).content)
    assert [i["name"] for i in described["inputs"]] == ["features"]
    assert described["devices"] == {
        "takes_devices": True,
        "max": 20,
        "accepts_ipv4_outside_inventory": False,
    }
    assert described["chosen_by_the_user_on_the_card"] == ["cred"]


def test_describe_unreleased_is_refused() -> None:
    out = _call(_box(released=FakeReleased(None)), "describe_workflow", workflow_id=5)
    assert out.is_error


def test_propose_builds_a_verifiable_proposal() -> None:
    out = _call(
        _box(), "propose_workflow_run", workflow_id=5, inputs={"features": "ospf"}, devices=["sw1"]
    )
    assert not out.is_error and out.proposal is not None
    assert out.proposal["kind"] == "workflow_run"
    assert out.proposal["devices"] == [{"name": "sw1", "ip": "10.0.0.1", "in_inventory": True}]
    assert out.proposal["credential_inputs"] == ["cred"]
    assert out.proposal["driver_choices"] == []  # only asked for addresses outside the inventory
    grant = verify_run_token(out.proposal["token"], user_id=9)
    assert (grant.workflow_id, grant.run_inputs) == (5, {"features": "ospf"})
    assert grant.devices == (ProposedDevice(ip="10.0.0.1", name="sw1"),)
    assert "NOT started" in out.content


@pytest.mark.parametrize("name", ["token", "devs", "cred"])
def test_propose_refuses_inputs_only_the_system_or_user_fills(name: str) -> None:
    out = _call(
        _box(),
        "propose_workflow_run",
        workflow_id=5,
        inputs={"features": "x", name: "t"},
        devices=["sw1"],
    )
    assert out.is_error and out.proposal is None


def test_propose_refuses_a_required_secret_only_the_user_can_give() -> None:
    attrs = ({"name": "pw", "type": "secret", "required": True},)
    wf = ReleasedWorkflow(5, "W", "d", None, attrs)
    out = _call(_box(released=FakeReleased(wf)), "propose_workflow_run", workflow_id=5)
    assert out.is_error and "workflow page" in out.content


def test_propose_refuses_a_required_credential_the_release_did_not_mark() -> None:
    attrs = ({"name": "cred", "type": "reference", "ref_kind": "credential", "required": True},)
    wf = ReleasedWorkflow(5, "W", "d", None, attrs)
    out = _call(_box(released=FakeReleased(wf)), "propose_workflow_run", workflow_id=5)
    assert out.is_error and "releaser" in out.content


def test_propose_without_a_devices_input_takes_no_devices() -> None:
    wf = ReleasedWorkflow(5, "W", "d", None, ())
    box = _box(released=FakeReleased(wf))
    assert _call(box, "propose_workflow_run", workflow_id=5, devices=["sw1"]).is_error
    assert not _call(box, "propose_workflow_run", workflow_id=5).is_error


def test_propose_with_a_devices_input_needs_a_device() -> None:
    out = _call(_box(), "propose_workflow_run", workflow_id=5, inputs={"features": "a"})
    assert out.is_error and "at least one device" in out.content


def test_propose_reports_invalid_inputs_and_unknown_devices() -> None:
    unknown = _call(
        _box(), "propose_workflow_run", workflow_id=5, inputs={"nope": 1}, devices=["sw1"]
    )
    missing = _call(_box(), "propose_workflow_run", workflow_id=5, devices=["sw1"])
    ghost = _call(
        _box(), "propose_workflow_run", workflow_id=5, inputs={"features": "a"}, devices=["ghost"]
    )
    assert unknown.is_error and missing.is_error and ghost.is_error
    assert all(o.proposal is None for o in (unknown, missing, ghost))


def test_an_address_outside_the_inventory_needs_the_release_to_allow_it() -> None:
    refused = _call(
        _box(),
        "propose_workflow_run",
        workflow_id=5,
        inputs={"features": "a"},
        devices=["10.9.9.9"],
    )
    assert refused.is_error and refused.proposal is None

    allowed = _call(
        _box(released=FakeReleased(_free_ip_workflow())),
        "propose_workflow_run",
        workflow_id=5,
        inputs={"features": "a"},
        devices=["10.9.9.9"],
    )
    assert not allowed.is_error and allowed.proposal is not None
    assert allowed.proposal["devices"] == [
        {"name": "10.9.9.9", "ip": "10.9.9.9", "in_inventory": False}
    ]
    assert "cisco_ios" in allowed.proposal["driver_choices"]


@pytest.mark.parametrize(
    "device", ["10.0.0.1,10.0.0.2", "10.0.0.1\n10.0.0.2", "a b", "x;rm", "10.0.0.0/24", ""]
)
def test_a_device_with_separators_never_reaches_the_reader(device: str) -> None:
    out = _call(
        _box(released=FakeReleased(_free_ip_workflow())),
        "propose_workflow_run",
        workflow_id=5,
        inputs={"features": "a"},
        devices=[device],
    )
    assert out.is_error and out.proposal is None


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


def test_result_needs_a_run_the_assistant_started_with_a_designated_step() -> None:
    for runs in (FakeRuns(node=None), FakeRuns(trigger="manual")):
        out = _call(_box(runs=runs), "get_run_result", run_id=1)
        assert out.is_error and "designated result step" in out.content
    assert _call(_box(runs=FakeRuns(denied=True)), "get_run_result", run_id=1).is_error


def test_result_follows_the_step_stored_on_the_run_not_the_current_release() -> None:
    """A later release may designate another step; an older run still answers with its own."""
    moved = ReleasedWorkflow(5, "W", "d", "other-step", ATTRS, devices_input="devs")
    out = _call(_box(released=FakeReleased(moved)), "get_run_result", run_id=1)
    assert not out.is_error and "+ b" in out.content

    unreleased_since = _call(_box(released=FakeReleased(None)), "get_run_result", run_id=1)
    assert not unreleased_since.is_error  # reading your own run does not need the release


def test_the_proposal_carries_the_stamp_and_the_inputs_that_will_run() -> None:
    attrs = (
        *ATTRS,
        {"name": "strict", "type": "boolean", "default": True},
        {"name": "profile", "type": "reference", "ref_kind": "credential", "default": "svc-ro"},
    )
    wf = ReleasedWorkflow(
        5, "W", "d", None, attrs, devices_input="devs", credential_inputs=("cred",),
        release_stamp="stamp-1",
    )  # fmt: skip
    out = _call(
        _box(released=FakeReleased(wf)),
        "propose_workflow_run",
        workflow_id=5,
        inputs={"features": "ospf"},
        devices=["sw1"],
    )
    assert not out.is_error and out.proposal is not None
    # defaults appear, including the hidden credential default; the user-filled inputs and the
    # secret do not
    assert out.proposal["inputs"] == {"features": "ospf", "strict": True, "profile": "svc-ro"}
    grant = verify_run_token(out.proposal["token"], user_id=9)
    assert grant.stamp == "stamp-1"
    assert grant.run_inputs == out.proposal["inputs"]


def test_a_long_list_says_it_was_cut_off() -> None:
    many = [ReleasedWorkflow(i, f"W{i}", "d", None, ()) for i in range(1, 61)]

    class Many(FakeReleased):
        async def list_released(self):
            return many

    listing = json.loads(_call(_box(released=Many()), "list_released_workflows").content)
    assert len(listing["workflows"]) == 50 and listing["total"] == 60
    assert "Only the first 50 of 60" in listing["note"]

    short = json.loads(_call(_box(), "list_released_workflows").content)
    assert "note" not in short and short["total"] == 1


@pytest.mark.parametrize("name", ["list_released_workflows", "describe_workflow", "get_run_result"])
def test_read_tools_are_registered(name: str) -> None:
    assert name in {t.name for t in build_released_workflow_tools()}


class _DiscoverRuns(FakeRuns):
    """A finished run whose designated step is a Discover Network / Exists in Nautobot step."""

    async def get_run(self, run_id):
        run = await super().get_run(run_id)
        record = {
            "visited": [
                {"name": "core1", "ip": "10.1.0.1", "depth": 0, "discovered_from": None,
                 "seed": True, "cdp_status": "ok"}
            ],
            "seen_not_visited": [
                {"name": "far", "ip": "172.16.0.9", "platform": "", "reason": "out_of_scope",
                 "seen_from": "core1", "depth": 1}
            ],
            "edges": [],
            "limits_hit": [],
            "truncated": False,
        }  # fmt: skip
        envelope = {
            "devices": {"d1": {"id": "d1", "name": "core1", "status": "ok"}},
            "metadata": {"disc.discovery": record},
        }
        step = {
            "step_node_id": "disc",
            "step_type": "exists-in-nautobot",
            "step_name": "Exists in Nautobot",
            "status": "success",
            "output": {"outcomes": {"exists": envelope, "non_existing": {"devices": {}}}},
        }
        return {**run, "ai_result_node_id": "disc", "step_results": [step]}


def _discover_box(*, addresses: bool) -> Toolbox:
    sharing = SharingPolicy(inventory=True, addresses=addresses, content=True)
    runs = _DiscoverRuns()
    extras: dict[str, Any] = {RELEASED_WORKFLOWS_KEY: FakeReleased()}
    extras.update(run_viewer_extras(runs, sharing, can_list_runs=True))
    ctx = ToolContext(user_id=9, redactor=Redactor(), extras=extras, sharing=sharing)
    return Toolbox(build_released_workflow_tools(), ctx)


def test_result_carries_the_crawl_record_of_a_discover_step() -> None:
    out = _call(_discover_box(addresses=True), "get_run_result", run_id=1)
    view = json.loads(out.content)["discovery"]
    assert [v["name"] for v in view["visited"]] == ["core1"]
    assert view["seen_by_reason"] == {"out_of_scope": 1}


def test_the_crawl_record_needs_the_addresses_switch_too() -> None:
    out = _call(_discover_box(addresses=False), "get_run_result", run_id=1)
    view = json.loads(out.content)["discovery"]
    assert view["not_shared"] == "device_addresses"
    assert "172.16.0.9" not in out.content

"""Workflow-builder tools + surface: what the model sees, the validation loop, secret handling."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from core.config import settings
from models.ai_assistant import WorkflowCanvasContext
from repositories.plugin_repository import PluginRepository
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.surfaces import build_workflow_editor_session
from services.ai_assistant.tools.base import ToolOutput
from services.ai_assistant.tools.workflow_tools import ReferencePermissionError
from services.ai_assistant.workflow_expand import WorkflowPlanIn, expand_plan
from services.plugin_registry.plugin_registry_service import PluginRegistryService


@dataclass
class FakeFinding:
    severity: str
    message: str
    code: str = "missing_required_field"
    tier: int = 1
    node_id: str | None = "inv"


@dataclass
class FakeOutcome:
    findings: list[FakeFinding]

    @property
    def has_errors(self) -> bool:
        return any(f.severity == "error" for f in self.findings)


class FakeValidator:
    def __init__(self, findings: list[FakeFinding] | None = None) -> None:
        self.findings = findings or []
        self.seen: list[tuple[list[dict], list[dict]]] = []

    async def validate(self, nodes, edges):
        self.seen.append((nodes, edges))
        return FakeOutcome(self.findings)


class FakeReferences:
    def __init__(self, denied: bool = False) -> None:
        self.denied = denied

    async def list_references(self, kind: str):
        if self.denied:
            raise ReferencePermissionError
        return {"credentials": [{"id": 3, "name": "lab-ssh", "type": "ssh"}]}.get(kind, [])


@pytest.fixture(scope="module")
def registry() -> PluginRegistryService:
    return PluginRegistryService(PluginRepository(plugins_file=settings.plugins_file))


def _canvas(registry, nodes: list[dict], edges: list[dict] | None = None) -> dict[str, list]:
    expanded = expand_plan(
        WorkflowPlanIn.model_validate({"nodes": nodes, "edges": edges or []}),
        current_nodes=[],
        current_edges=[],
        current_groups=[],
        current_static_attributes=[],
        registry=registry,
    )
    return {"nodes": expanded.nodes, "edges": expanded.edges}


INV = {"id": "inv", "kind": "get-nautobot-devices", "config": {"nautobot_source_id": "nautobot"}}
ATTRS = {"id": "attrs", "kind": "get-nautobot-attributes"}
EDGE = {"from": "inv", "outcome": "success", "to": "attrs"}


def _session(registry, canvas=None, validator=None, references=None, name="Backups"):
    canvas = canvas or {"nodes": [], "edges": []}
    context = WorkflowCanvasContext(
        surface="workflow_editor",
        name=name,
        canvas_nodes=canvas["nodes"],
        canvas_edges=canvas["edges"],
    )
    return build_workflow_editor_session(
        user_id=1,
        context=context,
        registry=registry,
        references=references or FakeReferences(),
        validator=validator or FakeValidator(),
    )


def _call(session, name: str, **input_: Any) -> ToolOutput:
    return asyncio.run(session.toolbox.execute(ToolCall("1", name, input_)))


# -- what the model is told ------------------------------------------------------------------


def test_prompt_carries_a_compact_view_without_layout_or_secrets(registry) -> None:
    canvas = _canvas(
        registry,
        [{**INV, "config": {**INV["config"], "password": "hunter2hunter2"}}, ATTRS],
        [EDGE],
    )

    system = _session(registry, canvas).system

    assert "<canvas_state>" in system and "get-nautobot-devices" in system
    assert "hunter2" not in system and "__SECRET_1__" in system
    assert "measured" not in system and "position" not in system
    assert "not instructions" in system


def test_all_six_tools_are_offered_with_inlined_schemas(registry) -> None:
    specs = {s.name: s for s in _session(registry).toolbox.specs()}

    assert set(specs) == {
        "get_workflow_reference",
        "list_steps",
        "get_step_schema",
        "list_references",
        "validate_workflow",
        "propose_workflow",
    }
    schema = specs["propose_workflow"].input_schema
    assert "$defs" not in schema and "$ref" not in str(schema)
    assert "nodes" in schema["properties"]["plan"]["properties"]


# -- read tools ----------------------------------------------------------------------------------


def test_reference_text_and_step_catalogue(registry) -> None:
    session = _session(registry)

    assert "compact plan" in _call(session, "get_workflow_reference").content
    listing = _call(session, "list_steps", search="nautobot").content
    assert "get-nautobot-devices | Get from Nautobot" in listing
    assert "step-group" not in _call(session, "list_steps").content  # decorations are hidden


def test_step_schema_lists_config_fields_outcomes_and_capabilities(registry) -> None:
    out = _call(_session(registry), "get_step_schema", step_id="get-nautobot-attributes")

    assert not out.is_error
    assert "outcomes: success, failure" in out.content
    assert "requires: ['identity']" in out.content
    assert "configuration (pluginConfig keys):" in out.content
    assert _call(_session(registry), "get_step_schema", step_id="nope").is_error


def test_references_are_listed_and_permission_checked(registry) -> None:
    ok = _call(_session(registry), "list_references", kind="credentials")
    denied = _call(
        _session(registry, references=FakeReferences(denied=True)),
        "list_references",
        kind="credentials",
    )

    assert '"lab-ssh"' in ok.content and "secret" not in ok.content.lower()
    assert denied.is_error
    assert _call(_session(registry), "list_references", kind="bogus").is_error


# -- validate / propose ----------------------------------------------------------------------------


def test_validate_reports_findings_and_flags_errors(registry) -> None:
    validator = FakeValidator(
        [FakeFinding("error", "'x' is required"), FakeFinding("warning", "w")]
    )
    session = _session(registry, validator=validator)

    out = _call(session, "validate_workflow", plan={"nodes": [INV], "edges": []})

    assert out.is_error and "1 error(s), 1 warning(s)" in out.content
    assert "missing_required_field" in out.content
    assert validator.seen  # validated the expanded canvas


def test_a_plan_with_validation_errors_is_not_proposed(registry) -> None:
    session = _session(registry, validator=FakeValidator([FakeFinding("error", "bad")]))

    out = _call(session, "propose_workflow", plan={"nodes": [INV]}, summary="s")

    assert out.is_error and out.proposal is None
    assert "nothing was proposed" in out.content


def test_a_clean_plan_becomes_a_proposal_with_changes_and_warnings(registry) -> None:
    validator = FakeValidator([FakeFinding("warning", "check this", code="w1", tier=4)])
    session = _session(registry, validator=validator)

    out = _call(
        session,
        "propose_workflow",
        plan={"nodes": [INV, ATTRS], "edges": [EDGE]},
        summary="Add devices and attributes",
    )

    assert not out.is_error and out.proposal is not None
    proposal = out.proposal
    assert proposal["kind"] == "workflow"
    assert [n["id"] for n in proposal["canvas_nodes"]] == ["inv", "attrs"]
    assert proposal["canvas_edges"][0]["sourceHandle"] == "success"
    assert [n["id"] for n in proposal["changes"]["nodes_added"]] == ["inv", "attrs"]
    assert proposal["warnings"] == [{"node_id": "inv", "code": "w1", "message": "check this"}]
    assert "NOT applied" in out.content


def test_structural_plan_errors_come_back_as_a_list_for_the_model(registry) -> None:
    out = _call(
        _session(registry),
        "propose_workflow",
        plan={"nodes": [{"id": "a", "kind": "no-such-step"}]},
        summary="s",
    )

    assert out.is_error and "Unknown step kind 'no-such-step'" in out.content


def test_an_unchanged_plan_is_rejected(registry) -> None:
    canvas = _canvas(registry, [INV, ATTRS], [EDGE])
    session = _session(registry, canvas)

    out = _call(
        session, "propose_workflow", plan={"nodes": [INV, ATTRS], "edges": [EDGE]}, summary="s"
    )

    assert out.is_error and "identical" in out.content


def test_secrets_round_trip_through_the_token_without_leaking_to_the_model(registry) -> None:
    canvas = _canvas(
        registry,
        [{**INV, "config": {**INV["config"], "password": "hunter2hunter2"}}],
    )
    session = _session(registry, canvas)

    out = _call(
        session,
        "propose_workflow",
        plan={
            "nodes": [
                {**INV, "config": {"nautobot_source_id": "other", "password": "__SECRET_1__"}}
            ]
        },
        summary="change the source",
    )

    assert not out.is_error and out.proposal is not None
    config = out.proposal["canvas_nodes"][0]["data"]["pluginConfig"]
    assert config == {"nautobot_source_id": "other", "password": "hunter2hunter2"}
    assert "hunter2" not in out.content and "__SECRET_" not in str(out.proposal)


def test_a_secret_token_cannot_be_moved_into_another_field(registry) -> None:
    canvas = _canvas(
        registry,
        [{**INV, "config": {**INV["config"], "password": "hunter2hunter2"}}],
    )
    session = _session(registry, canvas)

    out = _call(
        session,
        "propose_workflow",
        plan={
            "nodes": [
                {
                    **INV,
                    "config": {"nautobot_source_id": "__SECRET_1__", "password": "__SECRET_1__"},
                }
            ]
        },
        summary="move it",
    )

    assert out.is_error and out.proposal is None
    assert "nautobot_source_id" in out.content
    assert "hunter2" not in out.content


def test_a_literal_redaction_marker_is_never_proposed(registry) -> None:
    out = _call(
        _session(registry),
        "propose_workflow",
        plan={"nodes": [{**INV, "config": {"password": "***REDACTED***"}}]},
        summary="s",
    )

    assert out.is_error and "REDACTED" in out.content


def test_decorations_and_groups_survive_a_proposal(registry) -> None:
    canvas = _canvas(registry, [INV, ATTRS], [EDGE])
    label = {
        "id": "label-1",
        "type": "labelNode",
        "position": {"x": 0, "y": 0},
        "data": {"kind": "label"},
    }
    context = WorkflowCanvasContext(
        surface="workflow_editor",
        canvas_nodes=[*canvas["nodes"], label],
        canvas_edges=canvas["edges"],
        canvas_groups=[
            {"id": "g1", "title": "G", "nodeIds": ["inv", "attrs"], "position": {"x": 0, "y": 0}}
        ],
    )
    session = build_workflow_editor_session(
        user_id=1,
        context=context,
        registry=registry,
        references=FakeReferences(),
        validator=FakeValidator(),
    )

    out = _call(
        session,
        "propose_workflow",
        plan={
            "nodes": [{**INV, "config": {"nautobot_source_id": "other"}}, ATTRS],
            "edges": [EDGE],
        },
        summary="s",
    )

    assert out.proposal is not None
    assert label in out.proposal["canvas_nodes"]
    assert out.proposal["canvas_groups"][0]["nodeIds"] == ["inv", "attrs"]

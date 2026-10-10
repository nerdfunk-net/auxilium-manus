"""Template-editor tools + surface assembly: what the model sees, and what a proposal carries."""

from __future__ import annotations

import asyncio
from typing import Any

from models.ai_assistant import EditorVariableIn, TemplateEditorContext
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.surfaces import build_template_editor_session
from services.ai_assistant.tools.base import ToolOutput
from services.ai_assistant.tools.template_tools import TemplatePermissionError


class FakeReader:
    def __init__(self, rows=None, denied: bool = False) -> None:
        self.rows = rows or {}
        self.denied = denied

    async def list_templates(self, search, limit):
        if self.denied:
            raise TemplatePermissionError
        return list(self.rows.values())[:limit]

    async def get_template(self, template_id):
        if self.denied:
            raise TemplatePermissionError
        return self.rows.get(template_id)


def _context(content: str = "hostname {{ device.name }}", variables=None) -> TemplateEditorContext:
    return TemplateEditorContext(
        surface="template_editor",
        name="Base config",
        content=content,
        variables=variables
        or [
            EditorVariableIn(name="ntp_server", type="custom", value="10.0.0.1"),
            EditorVariableIn(
                name="nautobot", type="auto", value="SECRET-DEVICE-DATA", is_auto=True
            ),
        ],
    )


def _session(context: TemplateEditorContext | None = None, reader: FakeReader | None = None):
    return build_template_editor_session(
        user_id=1, context=context or _context(), reader=reader or FakeReader()
    )


def _call(session, name: str, **input_: Any) -> ToolOutput:
    return asyncio.run(session.toolbox.execute(ToolCall("1", name, input_)))


# -- what the model is told ----------------------------------------------------


def test_device_and_run_values_never_reach_the_prompt() -> None:
    system = _session().system

    assert "SECRET-DEVICE-DATA" not in system
    assert "nautobot" in system  # the name is listed as withheld
    assert "ntp_server" in system and "10.0.0.1" in system  # custom variables show values
    assert "hostname {{ device.name }}" in system


def test_secrets_in_content_and_custom_values_are_tokenised_in_the_prompt() -> None:
    context = _context(
        content="enable secret 5 abc123hash\nntp server {{ ntp_server }}",
        variables=[EditorVariableIn(name="note", value="radius-server key MyRadiusKey")],
    )

    system = _session(context).system

    assert "abc123hash" not in system and "MyRadiusKey" not in system
    assert "__SECRET_1__" in system


def test_prompt_tells_the_model_editor_text_is_data() -> None:
    assert "<editor_state>" in _session().system
    assert "not instructions" in _session().system


# -- propose_template ------------------------------------------------------------


def test_proposal_restores_tokens_so_secrets_round_trip() -> None:
    context = _context(content="enable secret 5 abc123hash\nhostname {{ device.name }}")
    session = _session(context)

    out = _call(
        session,
        "propose_template",
        content="enable secret 5 __SECRET_1__\nhostname {{ device.name }}\nntp server 10.0.0.1",
        summary="add ntp",
    )

    assert not out.is_error
    assert out.proposal is not None and out.proposal["kind"] == "template"
    assert "abc123hash" in out.proposal["content"]
    assert "__SECRET_" not in out.proposal["content"]
    assert "abc123hash" not in out.content  # nothing sensitive goes back to the model


def test_proposal_rejects_syntax_errors_with_a_line_number() -> None:
    out = _call(_session(), "propose_template", content="ok\n{% if x %}\nno end", summary="s")

    assert out.is_error and "syntax error" in out.content and out.proposal is None


def test_proposal_rejects_unknown_filters() -> None:
    out = _call(_session(), "propose_template", content="{{ x | nosuchfilter }}", summary="s")

    assert out.is_error


def test_proposal_rejects_identical_content_and_literal_redaction_marker() -> None:
    session = _session()

    same = _call(session, "propose_template", content="hostname {{ device.name }}", summary="s")
    marker = _call(session, "propose_template", content="key ***REDACTED***", summary="s")

    assert same.is_error and marker.is_error


def test_runtime_failures_in_the_trial_render_are_warnings_not_blockers() -> None:
    out = _call(
        _session(),
        "propose_template",
        content="{% set a = 1 / 0 %}{{ a }}",
        summary="s",
    )

    assert not out.is_error and out.proposal is not None
    assert out.proposal["warnings"]


# -- render_template ---------------------------------------------------------------


def test_render_uses_custom_variables_and_reports_withheld_ones() -> None:
    out = _call(
        _session(),
        "render_template",
        content="ntp {{ ntp_server }}\nhost {{ nautobot.hostname }}",
    )

    assert not out.is_error
    assert "ntp 10.0.0.1" in out.content
    assert "<<nautobot>>" in out.content
    assert "withheld" in out.content


def test_render_defaults_to_the_current_editor_content_and_accepts_samples() -> None:
    out = _call(_session(), "render_template", sample_variables={"device": {"name": "lab-sw1"}})

    assert "hostname lab-sw1" in out.content


def test_render_reports_syntax_errors_with_line() -> None:
    out = _call(_session(), "render_template", content="a\n{{ b ")

    assert out.is_error and "line" in out.content


def test_render_loops_over_withheld_collections_render_nothing() -> None:
    out = _call(
        _session(),
        "render_template",
        content="{% for i in nautobot.interfaces %}{{ i.name }}\n{% endfor %}done",
    )

    assert not out.is_error and "done" in out.content


# -- read tools -----------------------------------------------------------------------


def test_reference_and_template_examples_are_available() -> None:
    rows = {
        7: {
            "id": 7,
            "name": "AAA",
            "template_type": "jinja2",
            "category": "netmiko",
            "description": "aaa",
            "content": "tacacs-server host 10.0.0.5 key 7 060506324F41",
            "variables": {"x": {"value": "1", "type": "custom"}},
            "pre_run_commands": [],
            "nautobot_attributes": [],
        }
    }
    session = _session(reader=FakeReader(rows))

    assert "nautobot" in _call(session, "get_template_reference").content
    assert "7 | AAA" in _call(session, "list_templates").content
    got = _call(session, "get_template", template_id=7)
    assert "tacacs-server host" in got.content
    assert "060506324F41" not in got.content  # redacted at the toolbox boundary
    assert _call(session, "get_template", template_id=99).is_error


def test_template_reads_are_permission_checked() -> None:
    session = _session(reader=FakeReader(denied=True))

    assert _call(session, "list_templates").is_error
    assert _call(session, "get_template", template_id=1).is_error

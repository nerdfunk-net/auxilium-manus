"""Wiki notes in the workflow assistant: redaction, always-read prompt block, propose-only write."""

from __future__ import annotations

import asyncio

import pytest

from core.config import settings
from models.ai_assistant import WorkflowCanvasContext
from repositories.plugin_repository import PluginRepository
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.surfaces import build_workflow_editor_session
from services.plugin_registry.plugin_registry_service import PluginRegistryService

NOTES = (
    "Backs up 10.1.2.3/24 and fe80::1 (mac aa:bb:cc:dd:ee:ff).\n"
    "enable secret 9 hunter2hunter2\nrun at 12:30:45 only. Jinja {{ 8.8.8.8 }} stays.\n"
)


class NoRefs:
    async def list_references(self, kind: str):
        return []


class NoValidation:
    async def validate(self, nodes, edges):  # pragma: no cover - not used here
        raise AssertionError


class FakeNotes:
    def __init__(self, notes: str | None) -> None:
        self.notes = notes
        self.asked: list[int] = []

    async def read_notes(self, workflow_id: int) -> str | None:
        self.asked.append(workflow_id)
        return self.notes


@pytest.fixture(scope="module")
def registry() -> PluginRegistryService:
    return PluginRegistryService(PluginRepository(plugins_file=settings.plugins_file))


def make(registry, *, notes=NOTES, workflow_id=5, may_propose=True, sharing=None, known=()):
    reader = FakeNotes(notes)
    sess = build_workflow_editor_session(
        user_id=1,
        context=WorkflowCanvasContext(surface="workflow_editor", workflow_id=workflow_id, name="W"),
        registry=registry,
        references=NoRefs(),
        validator=NoValidation(),
        may_propose=may_propose,
        notes_reader=reader,
        saved_notes=notes,
        sharing=sharing,
        known_secrets=known,
    )
    return sess, reader


def call(sess, name, args=None):
    return asyncio.run(sess.toolbox.execute(ToolCall("1", name, args or {})))


def tool_names(sess) -> set[str]:
    return {s.name for s in sess.toolbox.specs()}


# -- Redactor addresses ---------------------------------------------------------------------


def test_addresses_round_trip_and_clock_time_and_jinja_untouched():
    r = Redactor()
    text = (
        "a 10.0.0.1/24 b 2001:db8::5 c aa:bb:cc:dd:ee:ff d 0011.2233.4455 t 12:30:45 {{ 1.1.1.1 }}"
    )
    masked = r.redact_addresses(text)
    assert "10.0.0.1" not in masked and "2001:db8" not in masked
    assert "aa:bb" not in masked and "0011.2233" not in masked
    assert "12:30:45" in masked and "{{ 1.1.1.1 }}" in masked and "/24" in masked
    assert r.restore(masked) == text


def test_has_unresolved_token():
    assert Redactor.has_unresolved_token("x __ADDR_9__")
    assert not Redactor.has_unresolved_token("plain")


# -- reading --------------------------------------------------------------------------------


def test_prompt_always_has_redacted_wiki(registry):
    sess, _ = make(registry)
    assert "<wiki_notes>" in sess.system
    assert "10.1.2.3" not in sess.system and "fe80::1" not in sess.system
    assert "hunter2hunter2" not in sess.system
    assert "__ADDR_1__" in sess.system and "{{ 8.8.8.8 }}" in sess.system


def test_addresses_visible_when_shared(registry):
    sess, _ = make(registry, sharing=SharingPolicy(inventory=True, addresses=True))
    assert "10.1.2.3" in sess.system
    assert "hunter2hunter2" not in sess.system  # credentials stay masked regardless


def test_known_secret_is_masked_even_bare(registry):
    sess, _ = make(registry, notes="the password is Sup3rS3cretX\n", known=["Sup3rS3cretX"])
    assert "Sup3rS3cretX" not in sess.system


def test_long_wiki_is_cut_in_prompt_but_tool_returns_more(registry):
    sess, _ = make(registry, notes="line of text\n" * 1500)
    assert "call get_workflow_notes" in sess.system
    out = call(sess, "get_workflow_notes")
    assert not out.is_error and len(out.content) > 8000


def test_get_notes_tool_redacts(registry):
    sess, reader = make(registry)
    out = call(sess, "get_workflow_notes")
    assert "10.1.2.3" not in out.content and "hunter2hunter2" not in out.content
    assert reader.asked == [5]


def test_unsaved_workflow_has_no_notes_and_no_propose_tool(registry):
    sess, reader = make(registry, workflow_id=None)
    assert "not saved yet" in sess.system
    assert "propose_workflow_notes" not in tool_names(sess)
    assert "no wiki" in call(sess, "get_workflow_notes").content.lower()
    assert reader.asked == []


def test_wiki_withheld_when_credentials_not_loadable(registry):
    sess, reader = make(registry, known=None)
    assert "hunter2hunter2" not in sess.system and "10.1.2.3" not in sess.system
    assert "withheld" in sess.system
    assert "propose_workflow_notes" not in tool_names(sess)
    assert "withheld" in call(sess, "get_workflow_notes").content
    assert reader.asked == []


def test_empty_wiki(registry):
    sess, _ = make(registry, notes="")
    assert "no wiki notes yet" in sess.system


def test_first_wiki_can_be_proposed_when_notes_are_empty(registry):
    # Regression: an empty wiki was read as "not readable" and the proposal was refused.
    sess, _ = make(registry, notes="")
    out = call(sess, "propose_workflow_notes", {"notes": "# W\n\n## Purpose\nx\n", "summary": "s"})
    assert not out.is_error and out.proposal is not None
    assert out.proposal["base_notes"] == ""


# -- writing --------------------------------------------------------------------------------


def test_template_tool_gives_the_standard_structure(registry):
    sess, _ = make(registry)
    out = call(sess, "get_wiki_template")
    assert not out.is_error
    for heading in ("## Purpose", "## Assumptions / prerequisites", "## Gotchas", "## Example"):
        assert heading in out.content
    assert "Get Backups" in out.content  # the finished example is included
    assert "get_wiki_template" in sess.system  # the prompt tells the model to read it first


def test_template_tool_only_with_propose(registry):
    assert "get_wiki_template" not in tool_names(make(registry, may_propose=False)[0])
    assert "get_wiki_template" not in tool_names(make(registry, workflow_id=None)[0])


def test_propose_not_offered_without_write(registry):
    sess, _ = make(registry, may_propose=False)
    assert "propose_workflow_notes" not in tool_names(sess)
    assert "get_workflow_notes" in tool_names(sess)


def test_propose_restores_tokens_and_builds_proposal(registry):
    sess, _ = make(registry)
    redacted = call(sess, "get_workflow_notes").content
    out = call(
        sess,
        "propose_workflow_notes",
        {"notes": redacted + "\n## Gotchas\nBe careful.\n", "summary": "Add gotchas"},
    )
    assert not out.is_error and out.proposal is not None
    assert out.proposal["kind"] == "workflow_notes"
    assert out.proposal["workflow_id"] == 5
    assert out.proposal["base_notes"] == NOTES
    assert out.proposal["notes"] == NOTES + "\n## Gotchas\nBe careful.\n"
    assert out.proposal["warnings"] == []
    assert "NOT saved" in out.content


def test_propose_rejects_unknown_token_marker_noop_and_oversize(registry):
    sess, _ = make(registry)
    bad = call(sess, "propose_workflow_notes", {"notes": "x __ADDR_99__", "summary": "s"})
    assert bad.is_error and "token" in bad.content
    bad = call(sess, "propose_workflow_notes", {"notes": "x ***REDACTED***", "summary": "s"})
    assert bad.is_error
    red = call(sess, "get_workflow_notes").content
    same = call(sess, "propose_workflow_notes", {"notes": red, "summary": "s"})
    assert same.is_error and "identical" in same.content
    big = call(sess, "propose_workflow_notes", {"notes": "a" * 100_001, "summary": "s"})
    assert big.is_error


def test_propose_warns_when_new_text_has_a_credential(registry):
    sess, _ = make(registry, notes="old\n")
    out = call(
        sess,
        "propose_workflow_notes",
        {"notes": "old\nenable secret 9 NewSecret12345\n", "summary": "s"},
    )
    assert out.proposal and len(out.proposal["warnings"]) == 1


def test_propose_when_wiki_unreadable(registry):
    sess, reader = make(registry)
    reader.notes = None
    out = call(sess, "propose_workflow_notes", {"notes": "new", "summary": "s"})
    assert out.is_error


def test_context_accepts_workflow_id_only_positive():
    WorkflowCanvasContext(surface="workflow_editor", workflow_id=3)
    with pytest.raises(ValueError):
        WorkflowCanvasContext(surface="workflow_editor", workflow_id=0)


# -- review fixes -----------------------------------------------------------------------------


def test_unreadable_wiki_is_not_reported_as_empty(registry):
    sess, reader = make(registry, notes=None)
    assert "cannot be read" in sess.system and "no wiki notes yet" not in sess.system
    out = call(sess, "get_workflow_notes")
    assert out.is_error and "cannot be read" in out.content
    assert reader.asked == [5]


def test_address_tokens_cannot_be_restored_into_a_canvas_field():
    from services.ai_assistant.redaction import SecretRelocationError

    r = Redactor()
    token = r.redact_addresses("gateway 10.1.2.3")
    token = token.removeprefix("gateway ")
    # Notes text may restore it (propose_workflow_notes) ...
    assert r.restore(token) == "10.1.2.3"
    # ... a workflow plan may not, in any field.
    with pytest.raises(SecretRelocationError):
        r.restore_data({"host": token}, scope="n1")


def test_cut_notes_never_splits_a_token_and_prefers_a_line_end():
    from services.ai_assistant.tools.workflow_notes_tools import cut_notes

    assert cut_notes("short", 100) == ("short", False)
    text = "a" * 10 + "__ADDR_12__" + "b" * 20
    cut, was_cut = cut_notes(text, 15)  # limit lands inside the token
    assert was_cut and cut == "a" * 10
    lines = "line one\nline two\nline three"
    cut, _ = cut_notes(lines, 20)
    assert cut == "line one\nline two"


def test_prompt_cut_keeps_tokens_whole(registry):
    notes = "x" * 7990 + " __SECRET_1__ tail\n" + "y" * 500
    sess, _ = make(registry, notes=notes)
    block = sess.system.split("<wiki_notes>")[1]
    assert "__SECRE" not in block.replace("__SECRET_1__", "")


def test_prompt_does_not_tell_the_model_to_follow_the_wiki(registry):
    sess, _ = make(registry)
    assert "follow what they say" not in sess.system
    assert "never copy a token from the wiki" in sess.system

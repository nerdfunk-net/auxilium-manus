"""Report tools on Ask the Net: gated rows, templates, and a proposal that signs the report."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from models.reports import DatasetInfo, FieldInfo, QueryResult, ReportQuery, ResultColumn
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.report_run_token import verify_report_token
from services.ai_assistant.tools.base import Toolbox, ToolContext
from services.ai_assistant.tools.report_general_tools import (
    REPORTS_GENERAL_KEY,
    GeneralReportsState,
    build_report_tools,
)
from services.ai_assistant.tools.report_tools import ReportAccessError, ReportNotFoundError
from services.reports.errors import ReportQueryError

DEVICES = DatasetInfo(
    name="devices",
    mode="device",
    fields=[
        FieldInfo(name="serial", type="string", null_share=0, sample_values=["SECRET"]),
        FieldInfo(name="location", type="string", null_share=0, sample_values=[]),
    ],
)
RESULT = QueryResult(
    columns=[
        ResultColumn(key="device_name", label="device_name", type="string"),
        ResultColumn(key="serial", label="serial", type="string"),
    ],
    rows=[["sw1", "S1"]],
)
TEMPLATE = {
    "id": 4,
    "name": "Inventory layout",
    "description": "Two blocks",
    "section_ids": ["devices", "totals"],
    "uses_section_list": False,
    "dynamic_lookup": False,
}


class FakeReader:
    def __init__(self, denied: bool = False) -> None:
        self.denied, self.ran = denied, []

    def _check(self) -> None:
        if self.denied:
            raise ReportAccessError

    async def list_sources(self):
        self._check()
        return [{"id": "nautobot", "label": "Nautobot"}, {"id": "report_data", "label": "DB"}]

    async def catalog(self, source_id):
        self._check()
        return [DEVICES]

    async def run_query(self, query):
        self._check()
        self.ran.append(query)
        return RESULT

    async def validate_query(self, query):
        self._check()
        if query.dataset != "devices":
            raise ReportQueryError(f"unknown dataset {query.dataset!r}")

    async def list_templates(self):
        self._check()
        return [TEMPLATE]

    async def get_template(self, template_id):
        self._check()
        if template_id != 4:
            raise ReportNotFoundError
        return TEMPLATE


def toolbox(*, sharing: SharingPolicy | None = None, denied=False, propose=True):
    reader = FakeReader(denied)
    ctx = ToolContext(
        user_id=7,
        redactor=Redactor(),
        extras={REPORTS_GENERAL_KEY: GeneralReportsState(reader)},
        sharing=sharing or SharingPolicy(),
    )
    return Toolbox(build_report_tools(can_propose=propose), ctx), reader, ctx


def call(box: Toolbox, tool: str, **input_: Any):
    return asyncio.run(box.execute(ToolCall("1", tool, input_)))


def query(**spec: Any) -> dict[str, Any]:
    return {"source": "nautobot", "dataset": "devices", **spec}


SECTION = {"title": "Serials", "query": query(select=["device_name", "serial"])}


def test_the_propose_tool_is_offered_only_to_someone_who_may_generate() -> None:
    assert "propose_report" in {t.name for t in build_report_tools(can_propose=True)}
    assert "propose_report" not in {t.name for t in build_report_tools(can_propose=False)}


def test_catalog_has_names_and_types_but_no_sample_values() -> None:
    box, _, _ = toolbox()
    out = call(box, "list_report_datasets", source="nautobot")
    assert "serial" in out.content and "SECRET" not in out.content


# -- gating of the rows ----------------------------------------------------------------------------


def test_nautobot_rows_need_the_inventory_switch() -> None:
    box, reader, _ = toolbox()
    out = call(box, "preview_report_query", query=query(select=["device_name", "location"]))
    assert "not_shared" in out.content
    assert reader.ran == []


def test_serials_need_the_addresses_switch_too() -> None:
    box, reader, _ = toolbox(sharing=SharingPolicy(inventory=True))
    for spec in (
        {"select": ["serial"]},
        {"group_by": ["serial"], "metrics": [{"op": "count"}]},
        {"filters": [{"field": "serial", "op": "not_null"}], "select": ["device_name"]},
        {},  # no select: every field, serial included
    ):
        assert "device_addresses" in call(box, "preview_report_query", query=query(**spec)).content
    assert reader.ran == []


def test_inventory_switch_alone_shows_non_address_fields() -> None:
    box, reader, _ = toolbox(sharing=SharingPolicy(inventory=True))
    out = call(box, "preview_report_query", query=query(select=["device_name", "location"]))
    assert "sw1" in out.content
    assert len(reader.ran) == 1


def test_with_both_switches_serials_are_shown() -> None:
    box, _, _ = toolbox(sharing=SharingPolicy(inventory=True, addresses=True))
    assert "S1" in call(box, "preview_report_query", query=query(select=["serial"])).content


def test_report_database_rows_need_the_report_data_switch() -> None:
    box, reader, _ = toolbox(sharing=SharingPolicy(inventory=True, addresses=True))
    out = call(box, "preview_report_query", query={"source": "report_data", "dataset": "inventory"})
    assert "report_data" in out.content and reader.ran == []
    allowed, reader2, _ = toolbox(sharing=SharingPolicy(report_data=True))
    call(allowed, "preview_report_query", query={"source": "report_data", "dataset": "inventory"})
    assert len(reader2.ran) == 1


def test_an_unknown_source_fails_closed() -> None:
    box, reader, _ = toolbox(sharing=SharingPolicy(inventory=True, addresses=True))
    out = call(box, "preview_report_query", query={"source": "future", "dataset": "x"})
    assert "not_shared" in out.content and reader.ran == []


def test_no_access_is_reported_not_raised() -> None:
    box, _, _ = toolbox(denied=True, sharing=SharingPolicy(inventory=True))
    assert call(box, "list_report_sources").is_error
    assert call(box, "list_report_templates").is_error
    assert call(box, "preview_report_query", query=query(select=["location"])).is_error


# -- templates and the proposal ----------------------------------------------------------------


def test_templates_are_listed_with_their_section_ids() -> None:
    box, _, _ = toolbox()
    assert json.loads(call(box, "list_report_templates").content)[0]["section_ids"] == [
        "devices",
        "totals",
    ]


def test_a_proposal_shows_a_card_and_signs_exactly_the_report() -> None:
    box, _, ctx = toolbox()
    out = call(
        box,
        "propose_report",
        name="Serial numbers",
        summary="All serials",
        sections=[SECTION],
    )
    assert not out.is_error
    proposal = out.proposal
    assert proposal["kind"] == "report_run"
    assert proposal["sections"] == [
        {
            "id": "s1",
            "title": "Serials",
            "source": "nautobot",
            "dataset": "devices",
            "presentation": "table",
        }
    ]
    grant = verify_report_token(proposal["token"], user_id=7)
    assert grant.report.name == "Serial numbers"
    assert grant.report.sections[0].query == ReportQuery.model_validate(SECTION["query"])
    assert "report_source:nautobot" in ctx.audit_refs
    assert "NOT generated" in out.content


def test_the_token_works_only_for_the_proposing_user() -> None:
    from services.ai_assistant.report_run_token import InvalidReportTokenError

    box, _, _ = toolbox()
    out = call(box, "propose_report", name="R", summary="s", sections=[SECTION])
    with pytest.raises(InvalidReportTokenError):
        verify_report_token(out.proposal["token"], user_id=8)


def test_an_invalid_query_is_sent_back_to_the_model() -> None:
    box, _, _ = toolbox()
    bad = {"title": "Bad", "query": query(select=["x"]) | {"dataset": "missing"}}
    out = call(box, "propose_report", name="R", summary="s", sections=[bad])
    assert out.is_error and "missing" in out.content and out.proposal is None


def test_a_template_needs_its_section_ids() -> None:
    box, _, _ = toolbox()
    out = call(box, "propose_report", name="R", summary="s", template_id=4, sections=[SECTION])
    assert out.is_error and "devices" in out.content and "totals" in out.content


def test_a_template_with_matching_ids_is_attached() -> None:
    box, _, _ = toolbox()
    sections = [{**SECTION, "id": "devices"}, {**SECTION, "id": "totals", "title": "Totals"}]
    out = call(box, "propose_report", name="R", summary="s", template_id=4, sections=sections)
    assert not out.is_error
    assert out.proposal["template"] == {"id": 4, "name": "Inventory layout"}
    assert verify_report_token(out.proposal["token"], user_id=7).report.template_id == 4


def test_an_unknown_template_is_refused() -> None:
    box, _, _ = toolbox()
    out = call(box, "propose_report", name="R", summary="s", template_id=9, sections=[SECTION])
    assert out.is_error and "list_report_templates" in out.content


def test_duplicate_section_ids_are_refused() -> None:
    box, _, _ = toolbox()
    out = call(
        box,
        "propose_report",
        name="R",
        summary="s",
        sections=[{**SECTION, "id": "a"}, {**SECTION, "id": "a"}],
    )
    assert out.is_error and "unique" in out.content


def test_a_proposal_needs_no_data_switch() -> None:
    box, reader, _ = toolbox(sharing=SharingPolicy())
    out = call(box, "propose_report", name="R", summary="s", sections=[SECTION])
    assert not out.is_error and reader.ran == []


def test_a_template_with_unknowable_section_ids_is_refused() -> None:
    """Review: it would be signed, generated and stored 'partial' after the click."""
    box, reader, _ = toolbox()
    dynamic = {**TEMPLATE, "id": 5, "section_ids": [], "dynamic_lookup": True}
    looping = {**dynamic, "id": 6, "uses_section_list": True}
    templates = {4: TEMPLATE, 5: dynamic, 6: looping}

    async def get_template(template_id):
        return templates[template_id]

    reader.get_template = get_template
    refused = call(box, "propose_report", name="R", summary="s", template_id=5, sections=[SECTION])
    assert refused.is_error and "cannot be known" in refused.content and refused.proposal is None
    # A template that also loops over every section needs no particular id.
    assert not call(
        box, "propose_report", name="R", summary="s", template_id=6, sections=[SECTION]
    ).is_error

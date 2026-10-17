"""Report tools: the catalog is always visible, values only with the report-data opt-in."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from models.ai_assistant import ReportsContext
from models.reports import DatasetInfo, FieldInfo, QueryResult, ReportQuery, ResultColumn
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.surfaces import build_reports_session
from services.ai_assistant.tools.report_tools import (
    ReportAccessError,
    ReportNotFoundError,
)
from services.reports.errors import ReportQueryError

CATALOG = [
    DatasetInfo(
        name="inventory",
        mode="device",
        fields=[
            FieldInfo(
                name="location", type="string", null_share=0.0, sample_values=["SECRET-SITE"]
            ),
            FieldInfo(name="ports", type="number", null_share=0.1, sample_values=["48"]),
        ],
        last_collected_at=None,
    )
]

RESULT = QueryResult(
    columns=[
        ResultColumn(key="location", label="location", type="string"),
        ResultColumn(key="snmp_password", label="snmp_password", type="string"),
        ResultColumn(key="devices", label="devices", type="number"),
    ],
    rows=[[f"dc{i}", "hunter2hunter2", i] for i in range(120)],
    truncated=False,
)

SNAPSHOT = {
    "id": 7,
    "name": "Fleet - now",
    "content": {
        "name": "Fleet",
        "description": None,
        "sections": [
            {
                "section": {
                    "id": "s1",
                    "title": "Per site",
                    "text": "Look at dc1",
                    "presentation": "table",
                },
                "status": "ok",
                "result": RESULT.model_dump(mode="json"),
                "error": None,
                "truncated": False,
            },
            {
                "section": {"id": "s2", "title": "Broken", "text": None, "presentation": "table"},
                "status": "error",
                "result": None,
                "error": "unknown dataset 'x'",
                "truncated": False,
            },
        ],
    },
}


class FakeReportReader:
    def __init__(self, denied: bool = False) -> None:
        self.denied = denied
        self.ran: list[ReportQuery] = []

    def _check(self) -> None:
        if self.denied:
            raise ReportAccessError

    async def catalog(self, source_id):
        self._check()
        return CATALOG

    async def run_query(self, query):
        self._check()
        self.ran.append(query)
        return RESULT

    async def validate_query(self, query):
        self._check()
        if query.dataset != "inventory":
            raise ReportQueryError(f"unknown dataset {query.dataset!r}")

    async def list_reports(self):
        self._check()
        return [
            {
                "id": 1,
                "name": "Fleet",
                "sections": [{"id": "s1", "title": "Per site", "dataset": "inventory"}],
                "snapshots": [
                    {"id": 7, "status": "complete", "generated_at": "2026-10-12T10:00:00Z"}
                ],
            }
        ]

    async def get_report(self, report_id):
        self._check()
        if report_id != 1:
            raise ReportNotFoundError
        return {"id": 1, "name": "Fleet", "sections": [{"id": "s1", "title": "Per site"}]}

    async def get_snapshot(self, snapshot_id):
        self._check()
        if snapshot_id != 7:
            raise ReportNotFoundError
        return SNAPSHOT


def _session(*, report_data=False, denied=False):
    reader = FakeReportReader(denied)
    session = build_reports_session(
        user_id=1,
        context=ReportsContext(surface="reports", source_id="report_data"),
        reader=reader,
        sharing=SharingPolicy(report_data=report_data),
    )
    return session, reader


def _call(session, tool: str, **input_: Any):
    return asyncio.run(session.toolbox.execute(ToolCall("1", tool, input_)))


QUERY = {"dataset": "inventory", "group_by": ["location"], "metrics": [{"op": "count"}]}


def test_surface_offers_the_report_tools() -> None:
    session, _ = _session()

    assert {s.name for s in session.toolbox.specs()} == {
        "list_datasets",
        "describe_dataset",
        "run_query",
        "list_reports",
        "get_report_results",
        "propose_query",
        "propose_report_outline",
        "propose_section_text",
    }


def test_catalog_tools_work_without_opt_in_and_never_send_sample_values() -> None:
    session, _ = _session()

    listed = _call(session, "list_datasets")
    described = _call(session, "describe_dataset", dataset="inventory")

    for out in (listed, described):
        assert not out.is_error
        assert "location" in out.content and "number" in out.content
        assert "SECRET-SITE" not in out.content and "48" not in out.content
    assert json.loads(listed.content)[0]["name"] == "inventory"


def test_describe_unknown_dataset_is_an_error() -> None:
    session, _ = _session()

    assert _call(session, "describe_dataset", dataset="nope").is_error


def test_run_query_is_not_shared_by_default_and_does_not_run() -> None:
    session, reader = _session()

    out = _call(session, "run_query", query=QUERY)

    assert json.loads(out.content)["not_shared"] == "report_data"
    assert out.withheld == ("report_data",)
    assert reader.ran == []


def test_run_query_with_opt_in_returns_capped_redacted_rows() -> None:
    session, reader = _session(report_data=True)

    out = _call(session, "run_query", query=QUERY)

    data = json.loads(out.content)
    assert len(reader.ran) == 1
    assert data["total_rows"] == 120
    assert len(data["rows"]) == 100
    assert data["rows"][0]["location"] == "dc0"
    assert "hunter2hunter2" not in out.content
    assert "100 of 120" in data["note"]


def test_run_query_reports_query_errors_to_the_model() -> None:
    session, reader = _session(report_data=True)

    async def bad(query):
        raise ReportQueryError("unknown field 'x'")

    reader.run_query = bad  # type: ignore[method-assign]

    out = _call(session, "run_query", query=QUERY)

    assert out.is_error and "unknown field 'x'" in out.content


def test_run_query_rejects_invalid_input() -> None:
    session, _ = _session(report_data=True)

    assert _call(session, "run_query", query={"dataset": "x", "bogus": 1}).is_error


def test_list_reports_shows_structure_without_opt_in() -> None:
    session, _ = _session()

    out = _call(session, "list_reports")

    assert "Per site" in out.content and "inventory" in out.content and not out.is_error


def test_get_report_results_is_gated() -> None:
    session, _ = _session()

    out = _call(session, "get_report_results", snapshot_id=7)

    assert json.loads(out.content)["not_shared"] == "report_data"


def test_get_report_results_with_opt_in() -> None:
    session, _ = _session(report_data=True)

    out = _call(session, "get_report_results", snapshot_id=7)

    data = json.loads(out.content)
    assert [s["id"] for s in data["sections"]] == ["s1", "s2"]
    assert len(data["sections"][0]["rows"]) == 50
    assert data["sections"][0]["total_rows"] == 120
    assert data["sections"][1]["error"] == "unknown dataset 'x'"
    assert "hunter2hunter2" not in out.content


def test_get_report_results_unknown_snapshot() -> None:
    session, _ = _session(report_data=True)

    assert _call(session, "get_report_results", snapshot_id=99).is_error


def test_propose_query_emits_a_proposal_without_needing_the_opt_in() -> None:
    session, reader = _session()

    out = _call(session, "propose_query", query=QUERY, summary="Devices per site")

    assert not out.is_error
    assert out.proposal is not None
    assert out.proposal["kind"] == "query"
    assert out.proposal["summary"] == "Devices per site"
    assert out.proposal["query"]["dataset"] == "inventory"
    assert reader.ran == []  # validated, never executed


def test_propose_query_with_an_invalid_query_goes_back_to_the_model() -> None:
    session, _ = _session()

    out = _call(session, "propose_query", query={**QUERY, "dataset": "nope"}, summary="x")

    assert out.is_error and out.proposal is None and "unknown dataset" in out.content


def test_access_denied_is_reported() -> None:
    session, _ = _session(report_data=True, denied=True)

    for name, args in (
        ("list_datasets", {}),
        ("list_reports", {}),
        ("run_query", {"query": QUERY}),
        ("get_report_results", {"snapshot_id": 7}),
        ("propose_query", {"query": QUERY, "summary": "x"}),
    ):
        assert _call(session, name, **args).is_error, name


def test_run_query_says_when_the_query_limit_itself_cut_the_result() -> None:
    session, reader = _session(report_data=True)

    async def limited(query):
        return QueryResult(columns=RESULT.columns, rows=RESULT.rows, truncated=True)

    reader.run_query = limited  # type: ignore[method-assign]

    data = json.loads(_call(session, "run_query", query=QUERY).content)

    assert "total_rows" not in data
    assert data["rows_returned"] == 120
    assert "At least" in data["note"] and "limit" in data["note"]


def test_propose_query_allows_one_sort_key_only() -> None:
    session, _ = _session()
    two = [{"key": "a", "direction": "asc"}, {"key": "b", "direction": "desc"}]

    out = _call(session, "propose_query", query={**QUERY, "order_by": two}, summary="x")

    assert out.is_error and out.proposal is None and "one sort" in out.content


OUTLINE = {
    "name": "Fleet overview",
    "description": "Monthly",
    "sections": [
        {"title": "Per site", "query": QUERY, "presentation": "bar", "text": "Devices per site"},
        {"title": "All", "query": QUERY},
    ],
    "summary": "Two sections",
}


def test_propose_report_outline_numbers_the_sections_and_never_saves() -> None:
    session, reader = _session()

    out = _call(session, "propose_report_outline", **OUTLINE)

    assert not out.is_error and out.proposal is not None
    assert out.proposal["kind"] == "report_outline"
    assert out.proposal["name"] == "Fleet overview"
    sections = out.proposal["sections"]
    assert [s["id"] for s in sections] == ["s1", "s2"]
    assert sections[0]["presentation"] == "bar" and sections[1]["presentation"] == "table"
    assert sections[1]["text"] is None
    assert reader.ran == []


def test_propose_report_outline_rejects_a_bad_section_query_naming_the_section() -> None:
    session, _ = _session()
    bad = {**OUTLINE, "sections": [{"title": "Oops", "query": {**QUERY, "dataset": "nope"}}]}

    out = _call(session, "propose_report_outline", **bad)

    assert out.is_error and out.proposal is None
    assert "Oops" in out.content and "unknown dataset" in out.content


def test_propose_report_outline_needs_at_least_one_section() -> None:
    session, _ = _session()

    out = _call(session, "propose_report_outline", **{**OUTLINE, "sections": []})

    assert out.is_error and out.proposal is None


def test_propose_section_text_for_a_saved_section() -> None:
    session, _ = _session()

    out = _call(
        session, "propose_section_text", report_id=1, section_id="s1", text="New text", summary="x"
    )

    assert not out.is_error and out.proposal is not None
    assert out.proposal == {
        "kind": "section_text",
        "report_id": 1,
        "section_id": "s1",
        "section_title": "Per site",
        "text": "New text",
        "summary": "x",
    }


def test_propose_section_text_unknown_report_or_section_goes_back_to_the_model() -> None:
    session, _ = _session()

    missing_report = _call(
        session, "propose_section_text", report_id=9, section_id="s1", text="t", summary="x"
    )
    missing_section = _call(
        session, "propose_section_text", report_id=1, section_id="zz", text="t", summary="x"
    )

    assert missing_report.is_error and missing_report.proposal is None
    assert missing_section.is_error and "s1" in missing_section.content


def test_new_proposal_tools_report_denied_access() -> None:
    session, _ = _session(denied=True)

    assert _call(session, "propose_report_outline", **OUTLINE).is_error
    assert _call(
        session, "propose_section_text", report_id=1, section_id="s1", text="t", summary="x"
    ).is_error


def test_tool_schemas_have_no_dangling_references() -> None:
    session, _ = _session()

    for spec in session.toolbox.specs():
        text = json.dumps(spec.input_schema)
        assert "$ref" not in text and "$defs" not in text and "discriminator" not in text, spec.name


def test_db_reader_checks_reports_read(monkeypatch) -> None:
    import contextlib

    from services.ai_assistant import report_reader
    from services.auth.rbac_service import RBACService

    opened: list[object] = []

    @contextlib.contextmanager
    def fake_session():
        opened.append(object())
        yield object()

    monkeypatch.setattr(report_reader, "SessionLocal", fake_session)
    allowed = {"value": False}
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a: allowed["value"])
    reader = report_reader.DbReportReader(1, "report_data")

    for call in (
        reader.catalog("report_data"),
        reader.list_reports(),
        reader.get_snapshot(1),
        reader.validate_query(ReportQuery(dataset="x")),
        reader.run_query(ReportQuery(dataset="x")),
    ):
        try:
            asyncio.run(call)
        except ReportAccessError:
            continue
        raise AssertionError("expected ReportAccessError")
    assert len(opened) == 5  # a session per call, each closed by its context manager

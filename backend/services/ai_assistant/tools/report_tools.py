"""Tools for the reports surface: explore the report catalog, read results, propose queries.

The catalog (dataset and field names and types) is always visible, like workflow definitions:
the model needs it to build a query. Values collected by Store for Report steps (query results and
report snapshots) are class "report data" and are replaced by a ``not_shared`` marker unless the
user opted in. Sample values of fields are never sent. Pure reads and proposals only; a proposed
query is validated but never run, and nothing is saved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from models.report_definitions import MAX_SECTION_TEXT, MAX_SECTIONS, Presentation
from models.reports import DatasetInfo, QueryResult, ReportQuery
from services.ai_assistant.data_sharing import DataClass, gated
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.reports.errors import ReportQueryError

MAX_ROWS_SHOWN = 100
MAX_SECTION_ROWS_SHOWN = 50
MAX_FIELD_CHARS = 500


class ReportAccessError(Exception):
    """The calling user may not read reports, or the source is unavailable."""


class ReportNotFoundError(Exception):
    """No such snapshot."""


class ReportReader(Protocol):
    async def catalog(self, source_id: str) -> list[DatasetInfo]: ...

    async def run_query(self, query: ReportQuery) -> QueryResult: ...

    async def validate_query(self, query: ReportQuery) -> None: ...

    async def list_reports(self) -> list[dict[str, Any]]: ...

    async def get_report(self, report_id: int) -> dict[str, Any]:
        """A saved report as ``{id, name, sections: [{id, title}]}``; may raise ReportNotFound."""
        ...

    async def get_snapshot(self, snapshot_id: int) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ReportsState:
    reader: ReportReader
    source_id: str


def _state(ctx: ToolContext) -> ReportsState:
    return ctx.extras["reports"]


# -- inputs -----------------------------------------------------------------------------------


class NoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DescribeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str = Field(min_length=1, max_length=100)


class RunQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: ReportQuery


class ResultsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: int = Field(ge=1)


class ProposeQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: ReportQuery
    summary: str = Field(min_length=1, max_length=500, description="What the query shows")


class OutlineSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    query: ReportQuery
    presentation: Presentation = "table"
    text: str | None = Field(default=None, max_length=MAX_SECTION_TEXT)


class ProposeOutlineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    sections: list[OutlineSection] = Field(min_length=1, max_length=MAX_SECTIONS)
    summary: str = Field(min_length=1, max_length=500, description="What the report covers")


class ProposeSectionTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: int = Field(ge=1)
    section_id: str = Field(min_length=1, max_length=64)
    text: str = Field(max_length=MAX_SECTION_TEXT, description="The complete new section text")
    summary: str = Field(min_length=1, max_length=500, description="What changed in the text")


# -- helpers ----------------------------------------------------------------------------------

_NO_ACCESS = ToolOutput(
    "You cannot read reports here (missing permission or the source is unavailable).",
    is_error=True,
)


def _json(value: Any) -> str:
    return json.dumps(value, default=str, indent=1)


def _cap(value: Any) -> Any:
    if isinstance(value, str):
        return value[:MAX_FIELD_CHARS] + "…" if len(value) > MAX_FIELD_CHARS else value
    if isinstance(value, dict):
        return {k: _cap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_cap(v) for v in value]
    return value


def _dataset_view(dataset: DatasetInfo) -> dict[str, Any]:
    """Names and types only: sample values and null shares describe the data, so they stay out."""
    return {
        "name": dataset.name,
        "mode": dataset.mode,
        "fields": [{"name": f.name, "type": f.type} for f in dataset.fields],
        "last_collected_at": dataset.last_collected_at,
    }


def _rows_as_dicts(columns: list[dict[str, Any]], rows: list[list[Any]]) -> list[dict[str, Any]]:
    """Rows keyed by column so the structured redactor can mask secret-named columns."""
    keys = [c["key"] for c in columns]
    return [dict(zip(keys, row, strict=False)) for row in rows]


# -- handlers ---------------------------------------------------------------------------------


async def _list_datasets(ctx: ToolContext, args: NoInput) -> ToolOutput:
    state = _state(ctx)
    try:
        datasets = await state.reader.catalog(state.source_id)
    except ReportAccessError:
        return _NO_ACCESS
    if not datasets:
        return ToolOutput("No datasets yet: no Store for Report step has collected data.")
    return ToolOutput(_json([_dataset_view(d) for d in datasets]))


async def _describe_dataset(ctx: ToolContext, args: DescribeInput) -> ToolOutput:
    state = _state(ctx)
    try:
        datasets = await state.reader.catalog(state.source_id)
    except ReportAccessError:
        return _NO_ACCESS
    for dataset in datasets:
        if dataset.name == args.dataset:
            return ToolOutput(_json(_dataset_view(dataset)))
    return ToolOutput(f"Unknown dataset {args.dataset!r}. Use list_datasets.", is_error=True)


async def _run_query(ctx: ToolContext, args: RunQueryInput) -> ToolOutput:
    blocked = gated(ctx.sharing, DataClass.REPORT_DATA, True)
    if blocked is not True:
        return ToolOutput(_json(blocked))
    ctx.audit_refs.add(f"report_source:{_state(ctx).source_id}")
    try:
        result = await _state(ctx).reader.run_query(args.query)
    except ReportAccessError:
        return _NO_ACCESS
    except ReportQueryError as exc:
        return ToolOutput(f"The query is invalid: {exc}", is_error=True)
    columns = [c.model_dump() for c in result.columns]
    shown = result.rows[:MAX_ROWS_SHOWN]
    payload: dict[str, Any] = {
        "columns": [c["key"] for c in columns],
        "rows": _rows_as_dicts(columns, shown),
    }
    if result.truncated:
        # The query limit cut the result, so the row count is only a lower bound.
        payload["rows_returned"] = len(result.rows)
        payload["note"] = (
            f"At least {len(result.rows)} rows matched (the query limit was reached)"
            + (f"; showing {len(shown)}" if len(shown) < len(result.rows) else "")
            + ". Use group_by + metrics for exact totals, or add filters."
        )
    else:
        payload["total_rows"] = len(result.rows)
        if len(shown) < len(result.rows):
            payload["note"] = (
                f"Showing {len(shown)} of {len(result.rows)} rows. Summarize (group_by + "
                "metrics) for exact totals instead of counting rows."
            )
    truncated = result.truncated or len(shown) < len(result.rows)
    return ToolOutput(_json(_cap(ctx.redactor.redact_data(payload))), truncated=truncated)


async def _list_reports(ctx: ToolContext, args: NoInput) -> ToolOutput:
    try:
        reports = await _state(ctx).reader.list_reports()
    except ReportAccessError:
        return _NO_ACCESS
    if not reports:
        return ToolOutput("No saved reports.")
    return ToolOutput(_json(reports))


def _section_view(entry: dict[str, Any]) -> dict[str, Any]:
    section = entry["section"]
    view: dict[str, Any] = {
        "id": section["id"],
        "title": section["title"],
        "text": section.get("text"),
        "status": entry["status"],
    }
    if entry.get("error"):
        view["error"] = entry["error"]
    result = entry.get("result")
    if result:
        rows = result["rows"]
        view["columns"] = [c["key"] for c in result["columns"]]
        view["total_rows"] = len(rows)
        view["rows"] = _rows_as_dicts(result["columns"], rows[:MAX_SECTION_ROWS_SHOWN])
        if len(rows) > MAX_SECTION_ROWS_SHOWN or entry.get("truncated"):
            view["note"] = (
                f"Showing {min(len(rows), MAX_SECTION_ROWS_SHOWN)} of {len(rows)} stored rows."
            )
    return view


async def _get_report_results(ctx: ToolContext, args: ResultsInput) -> ToolOutput:
    blocked = gated(ctx.sharing, DataClass.REPORT_DATA, True)
    if blocked is not True:
        return ToolOutput(_json(blocked))
    try:
        snapshot = await _state(ctx).reader.get_snapshot(args.snapshot_id)
    except ReportAccessError:
        return _NO_ACCESS
    except ReportNotFoundError:
        return ToolOutput("That snapshot does not exist.", is_error=True)
    content = snapshot["content"]
    payload = {
        "snapshot": {k: snapshot.get(k) for k in ("id", "name")},
        "sections": [_section_view(e) for e in content["sections"]],
    }
    return ToolOutput(_json(_cap(ctx.redactor.redact_data(payload))))


async def _propose_query(ctx: ToolContext, args: ProposeQueryInput) -> ToolOutput:
    state = _state(ctx)
    if len(args.query.order_by) > 1:
        # The query builder that applies a proposal holds a single sort key.
        return ToolOutput(
            "Use at most one sort key (order_by): the query builder supports one sort. "
            "Fix it and propose again.",
            is_error=True,
        )
    try:
        await state.reader.validate_query(args.query)
    except ReportAccessError:
        return _NO_ACCESS
    except ReportQueryError as exc:
        return ToolOutput(f"The query is invalid: {exc}. Fix it and propose again.", is_error=True)
    proposal = {
        "kind": "query",
        "query": args.query.model_dump(mode="json"),
        "summary": args.summary,
    }
    return ToolOutput(
        "The query was checked and shown to the user. It is not applied until they click Apply.",
        proposal=proposal,
    )


async def _propose_report_outline(ctx: ToolContext, args: ProposeOutlineInput) -> ToolOutput:
    state = _state(ctx)
    for section in args.sections:
        if len(section.query.order_by) > 1:
            return ToolOutput(
                f"Section {section.title!r}: use at most one sort key (order_by). "
                "Fix it and propose again.",
                is_error=True,
            )
        try:
            await state.reader.validate_query(section.query)
        except ReportAccessError:
            return _NO_ACCESS
        except ReportQueryError as exc:
            return ToolOutput(
                f"Section {section.title!r}: the query is invalid: {exc}. "
                "Fix it and propose again.",
                is_error=True,
            )
    proposal = {
        "kind": "report_outline",
        "name": args.name,
        "description": args.description,
        "sections": [
            {
                "id": f"s{index}",
                "title": section.title,
                "query": section.query.model_dump(mode="json"),
                "presentation": section.presentation,
                "text": section.text,
            }
            for index, section in enumerate(args.sections, start=1)
        ],
        "summary": args.summary,
    }
    return ToolOutput(
        "The outline was checked and shown to the user. Nothing is saved until they apply it "
        "and save the report themselves.",
        proposal=proposal,
    )


async def _propose_section_text(ctx: ToolContext, args: ProposeSectionTextInput) -> ToolOutput:
    try:
        report = await _state(ctx).reader.get_report(args.report_id)
    except ReportAccessError:
        return _NO_ACCESS
    except ReportNotFoundError:
        return ToolOutput("That report does not exist. Use list_reports.", is_error=True)
    titles = {section["id"]: section["title"] for section in report["sections"]}
    if args.section_id not in titles:
        known = ", ".join(sorted(titles)) or "none"
        return ToolOutput(
            f"Report {args.report_id} has no section {args.section_id!r} (sections: {known}).",
            is_error=True,
        )
    proposal = {
        "kind": "section_text",
        "report_id": args.report_id,
        "section_id": args.section_id,
        "section_title": titles[args.section_id],
        "text": args.text,
        "summary": args.summary,
    }
    return ToolOutput(
        "The text was shown to the user. It is not applied or saved until they accept it.",
        proposal=proposal,
    )


REPORT_TOOLS: tuple[Tool, ...] = (
    Tool(
        "list_datasets",
        "Datasets available for reports: name, grain (device = one row per device, items = one "
        "row per list element) and fields with their types. No values.",
        NoInput,
        _list_datasets,
    ),
    Tool(
        "describe_dataset",
        "Fields and types of one dataset. No values.",
        DescribeInput,
        _describe_dataset,
    ),
    Tool(
        "run_query",
        "Run a report query and read its result rows (up to 100). Returns not_shared unless the "
        "user enabled 'Report data'. For counts and totals use group_by + metrics, not row "
        "counting.",
        RunQueryInput,
        _run_query,
    ),
    Tool(
        "list_reports",
        "Saved reports: sections (title, dataset) and their recent snapshots (id, status, time).",
        NoInput,
        _list_reports,
    ),
    Tool(
        "get_report_results",
        "The stored results of one report snapshot, section by section. Returns not_shared unless "
        "the user enabled 'Report data'.",
        ResultsInput,
        _get_report_results,
    ),
    Tool(
        "propose_query",
        "Check a query against the catalog and show it to the user, who can apply it to the "
        "query builder. It does not run the query and does not need 'Report data'.",
        ProposeQueryInput,
        _propose_query,
    ),
    Tool(
        "propose_report_outline",
        "Propose a new report: a name and ordered sections, each with a title, a query, a "
        "presentation (table, number, bar, line) and optional text. Every query is checked "
        "against the catalog. The user can open it in the report editor, review and save it; "
        "nothing is saved or run by this tool and it does not need 'Report data'.",
        ProposeOutlineInput,
        _propose_report_outline,
    ),
    Tool(
        "propose_section_text",
        "Propose the complete new text for one section of a saved report (ids from "
        "list_reports). The user reviews it in the report editor and saves it themselves.",
        ProposeSectionTextInput,
        _propose_section_text,
    ),
)

"""Report tools for Ask the Net: ask what a report can contain, try a query, propose a report.

Ask the Net can answer "write a report that lists the serial numbers of the network devices" from
two report sources: ``nautobot`` (live Nautobot datasets) and ``report_data`` (facts that Store for
Report steps collected). The catalog (dataset and field names) is always visible; values are gated
like everywhere else (Nautobot: the inventory switch, plus the addresses switch for serials and
addresses; stored report data: the report-data switch). ``propose_report`` shows a card and signs
the report; nothing is generated, stored or sent until the user clicks Generate, and the rows of a
generated report go from the server to the user, not through the model
(doc/AI_TOOL_CHAIN.md §53). Pure reads and proposals only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from models.report_definitions import (
    MAX_SECTION_TEXT,
    MAX_SECTIONS,
    Presentation,
    ReportDefinitionCreate,
    ReportSection,
)
from models.reports import DatasetInfo, QueryResult, ReportQuery
from services.ai_assistant.report_run_token import issue_report_token
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.report_gating import blocked_by_sharing
from services.ai_assistant.tools.report_tools import (
    MAX_ROWS_SHOWN,
    ReportAccessError,
    ReportNotFoundError,
    _cap,
    _dataset_view,
    _json,
    _rows_as_dicts,
)
from services.reports.errors import ReportQueryError

REPORTS_GENERAL_KEY = "reports_general"

_NO_ACCESS = ToolOutput(
    "You cannot read reports here (missing permission, or the source is not available).",
    is_error=True,
)


class GeneralReportReader(Protocol):
    async def list_sources(self) -> list[dict[str, str]]: ...

    async def catalog(self, source_id: str) -> list[DatasetInfo]: ...

    async def run_query(self, query: ReportQuery) -> QueryResult: ...

    async def validate_query(self, query: ReportQuery) -> None: ...

    async def list_templates(self) -> list[dict[str, Any]]: ...

    async def get_template(self, template_id: int) -> dict[str, Any]:
        """One active report template; raises ``ReportNotFoundError`` for any other."""
        ...


@dataclass(frozen=True)
class GeneralReportsState:
    reader: GeneralReportReader


def _state(ctx: ToolContext) -> GeneralReportsState:
    return ctx.extras[REPORTS_GENERAL_KEY]


# -- inputs -----------------------------------------------------------------------------------


class NoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(
        min_length=1, max_length=64, description="A source id from list_report_sources."
    )


class RunReportQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: ReportQuery


class ProposedSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$",
        description="Section id; needed to match a report template. Default s1, s2, ...",
    )
    title: str = Field(min_length=1, max_length=200)
    query: ReportQuery
    presentation: Presentation = "table"
    text: str | None = Field(default=None, max_length=MAX_SECTION_TEXT)


class ProposeReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    sections: list[ProposedSection] = Field(min_length=1, max_length=MAX_SECTIONS)
    template_id: int | None = Field(
        default=None, ge=1, description="A report template id from list_report_templates."
    )
    summary: str = Field(min_length=1, max_length=500, description="What the report covers")


# -- handlers ---------------------------------------------------------------------------------


async def _list_sources(ctx: ToolContext, args: NoInput) -> ToolOutput:
    try:
        return ToolOutput(_json(await _state(ctx).reader.list_sources()))
    except ReportAccessError:
        return _NO_ACCESS


async def _list_datasets(ctx: ToolContext, args: SourceInput) -> ToolOutput:
    try:
        datasets = await _state(ctx).reader.catalog(args.source)
    except ReportAccessError:
        return _NO_ACCESS
    if not datasets:
        return ToolOutput("No datasets in this source yet.")
    return ToolOutput(_json([_dataset_view(d) for d in datasets]))


async def _run_query(ctx: ToolContext, args: RunReportQueryInput) -> ToolOutput:
    query = args.query
    marker = blocked_by_sharing(ctx.sharing, query)
    if marker is not None:
        return ToolOutput(_json(marker))
    ctx.audit_refs.add(f"report_source:{query.source}")
    try:
        result = await _state(ctx).reader.run_query(query)
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
    cut = len(shown) < len(result.rows)
    if result.truncated:
        payload["note"] = (
            f"At least {len(result.rows)} rows matched (the query limit was reached); showing "
            f"{len(shown)}. Use group_by + metrics for exact totals, or add filters."
        )
    else:
        payload["total_rows"] = len(result.rows)
        if cut:
            payload["note"] = (
                f"Showing {len(shown)} of {len(result.rows)} rows. Summarize (group_by + "
                "metrics) for exact totals instead of counting rows."
            )
    return ToolOutput(
        _json(_cap(ctx.redactor.redact_data(payload))), truncated=cut or result.truncated
    )


async def _list_templates(ctx: ToolContext, args: NoInput) -> ToolOutput:
    try:
        templates = await _state(ctx).reader.list_templates()
    except ReportAccessError:
        return _NO_ACCESS
    if not templates:
        return ToolOutput("There are no report templates; the built-in layout is used.")
    return ToolOutput(_json(templates))


def _section_ids(sections: list[ProposedSection]) -> list[str]:
    return [s.id or f"s{index}" for index, s in enumerate(sections, start=1)]


async def _propose_report(ctx: ToolContext, args: ProposeReportInput) -> ToolOutput:
    reader = _state(ctx).reader
    ids = _section_ids(args.sections)
    if len(set(ids)) != len(ids):
        return ToolOutput("Section ids must be unique. Fix them and propose again.", is_error=True)
    try:
        for section in args.sections:
            await reader.validate_query(section.query)
        template = await reader.get_template(args.template_id) if args.template_id else None
    except ReportAccessError:
        return _NO_ACCESS
    except ReportQueryError as exc:
        return ToolOutput(f"A query is invalid: {exc}. Fix it and propose again.", is_error=True)
    except ReportNotFoundError:
        return ToolOutput(
            "That report template does not exist or is not active. Use list_report_templates.",
            is_error=True,
        )
    if template is not None and template["dynamic_lookup"] and not template["section_ids"]:
        if not template["uses_section_list"]:
            return ToolOutput(
                f"The template {template['name']!r} looks its sections up by a variable, so the "
                "section ids it needs cannot be known. Propose the report without this template "
                "and tell the user it has to be used from the Reports app.",
                is_error=True,
            )
    if template is not None:
        missing = [i for i in template["section_ids"] if i not in ids]
        if missing:
            return ToolOutput(
                f"The template {template['name']!r} reads the sections {template['section_ids']}; "
                f"missing: {missing}. Give the sections these ids, or pick another template.",
                is_error=True,
            )
    try:
        report = ReportDefinitionCreate(
            name=args.name,
            description=args.description,
            template_id=args.template_id,
            sections=[
                ReportSection(
                    id=section_id,
                    title=section.title,
                    query=section.query,
                    presentation=section.presentation,
                    text=section.text,
                )
                for section_id, section in zip(ids, args.sections, strict=True)
            ],
        )
    except ValidationError as exc:
        reason = exc.errors()[0]["msg"] if exc.errors() else "invalid"
        return ToolOutput(f"The report is not valid: {reason}.", is_error=True)
    token, expires_at = issue_report_token(user_id=ctx.user_id, report=report)
    for section in report.sections:
        ctx.audit_refs.add(f"report_source:{section.query.source}")
    proposal = {
        "kind": "report_run",
        "token": token,
        "expires_at": expires_at,
        "name": report.name,
        "description": report.description,
        "summary": args.summary,
        "template": {"id": template["id"], "name": template["name"]} if template else None,
        "sections": [
            {
                "id": s.id,
                "title": s.title,
                "source": s.query.source,
                "dataset": s.query.dataset,
                "presentation": s.presentation,
            }
            for s in report.sections
        ],
    }
    message = (
        f"A card for the report '{report.name}' was shown to the user with Generate/Reject. "
        "The report is NOT generated yet; do not say it was. When they click Generate it is "
        "created from the data as it is then, and they can open it and download it as PDF or "
        "CSV from the card. You do not see the rows of the generated report. Briefly say what "
        "the report contains."
    )
    return ToolOutput(message, proposal=proposal)


def build_report_tools(*, can_propose: bool) -> tuple[Tool, ...]:
    tools = [
        Tool(
            "list_report_sources",
            "The places a report can read from: 'nautobot' (the documented network, read live) "
            "and 'report_data' (facts that workflows collected from the devices).",
            NoInput,
            _list_sources,
        ),
        Tool(
            "list_report_datasets",
            "Datasets of one report source: name, grain (device = one row per device, items = "
            "one row per list element) and the fields with their types. No values.",
            SourceInput,
            _list_datasets,
        ),
        Tool(
            "preview_report_query",
            "Try a report query and read its first rows (up to 100). The query has a source, a "
            "dataset, filters, and either group_by + metrics (summary) or select (list). Returns "
            "not_shared unless the user enabled the matching data switch. Use it to check "
            "that a query returns what the report should show, not to write the report.",
            RunReportQueryInput,
            _run_query,
        ),
        Tool(
            "list_report_templates",
            "Report templates (layouts) the user's organisation made: id, name, description and "
            "the section ids each one reads. A report that uses a template must have sections "
            "with exactly those ids.",
            NoInput,
            _list_templates,
        ),
    ]
    if can_propose:
        tools.append(
            Tool(
                "propose_report",
                "Propose a report: a name, sections (each a title, a checked query and a "
                "presentation of table, number, bar or line, with an id when a template needs "
                "it) and optionally a template id. Shows the user a card; nothing is generated "
                "until they click Generate, and then they can download it as PDF or CSV.",
                ProposeReportInput,
                _propose_report,
            )
        )
    return tuple(tools)

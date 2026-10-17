"""Rendering a report snapshot through a Jinja2 (Markdown) template."""

from __future__ import annotations

from datetime import UTC, datetime

from models.report_definitions import ReportSection, SnapshotSection
from models.reports import QueryResult, ReportQuery, ResultColumn
from services.ai_assistant.template_render import render_lenient
from services.reports.report_renderer import (
    DEFAULT_TEMPLATE,
    build_render_context,
    markdown_table,
    render_report_body,
)

NOW = datetime(2026, 10, 12, 9, 30, tzinfo=UTC)


def _section(sid: str, title: str = "T", text: str | None = None) -> ReportSection:
    return ReportSection(
        id=sid,
        title=title,
        text=text,
        query=ReportQuery(dataset="inventory"),
    )


def _ok(sid: str, columns: list[tuple[str, str]], rows: list[list], **kw) -> SnapshotSection:
    result = QueryResult(
        columns=[ResultColumn(key=k, label=k.upper(), type=t) for k, t in columns],  # type: ignore[arg-type]
        rows=rows,
    )
    return SnapshotSection(
        section=_section(sid, kw.pop("title", "T"), kw.pop("text", None)),
        status="ok",
        result=result,
        truncated=kw.pop("truncated", False),
    )


def _failed(sid: str) -> SnapshotSection:
    return SnapshotSection(section=_section(sid), status="error", error="unknown dataset 'x'")


def _context(*sections: SnapshotSection) -> dict:
    return build_render_context(
        name="Fleet",
        description="All sites",
        generated_at=NOW,
        generated_by="alice",
        sections=list(sections),
    )


def test_context_exposes_report_and_sections_by_id_and_in_order() -> None:
    ctx = _context(
        _ok("per-site", [("location", "string"), ("devices", "number")], [["dc1", 2], ["dc2", 1]]),
        _failed("broken"),
    )

    assert ctx["report"] == {
        "name": "Fleet",
        "description": "All sites",
        "generated_at": "2026-10-12T09:30:00+00:00",
        "generated_by": "alice",
    }
    assert [s["id"] for s in ctx["section_list"]] == ["per-site", "broken"]
    site = ctx["sections"]["per-site"]
    assert site["rows"] == [{"location": "dc1", "devices": 2}, {"location": "dc2", "devices": 1}]
    assert site["row_count"] == 2
    assert site["first"] == {"location": "dc1", "devices": 2}
    assert site["value"] == 2
    assert [c["key"] for c in site["columns"]] == ["location", "devices"]
    assert ctx["sections"]["broken"]["status"] == "error"
    assert ctx["sections"]["broken"]["rows"] == []
    assert ctx["sections"]["broken"]["error"] == "unknown dataset 'x'"
    assert ctx["sections"]["broken"]["value"] is None


def test_value_is_the_first_numeric_cell_of_the_first_row() -> None:
    ctx = _context(_ok("s", [("name", "string"), ("n", "number")], [["a", 7]]))
    empty = _context(_ok("s", [("n", "number")], []))

    assert ctx["sections"]["s"]["value"] == 7
    assert empty["sections"]["s"]["value"] is None
    assert empty["sections"]["s"]["first"] is None


def test_markdown_table_escapes_cells_and_handles_empty_results() -> None:
    columns = [
        ResultColumn(key="a", label="A|B", type="string"),
        ResultColumn(key="n", label="n", type="number"),
    ]

    table = markdown_table(columns, [["x|y\nz", None], [True, 1.5]])

    assert table.splitlines() == [
        "| A\\|B | n |",
        "| --- | --- |",
        "| x\\|y z |  |",
        "| true | 1.5 |",
    ]
    assert markdown_table(columns, []) == "_No rows._"


def test_default_template_renders_every_section() -> None:
    ctx = _context(
        _ok(
            "a",
            [("location", "string"), ("devices", "number")],
            [["dc1", 2]],
            title="Per site",
            text="Devices by site",
        ),
        _failed("b"),
    )

    out = render_lenient(DEFAULT_TEMPLATE, ctx, strict=True)

    assert out.ok, out.error
    assert out.output.startswith("# Fleet")
    assert "All sites" in out.output
    assert "## Per site" in out.output
    assert "Devices by site" in out.output
    assert "| dc1 | 2 |" in out.output
    assert "unknown dataset 'x'" in out.output


def test_strict_mode_reports_a_missing_variable() -> None:
    ctx = _context(_ok("a", [("n", "number")], [[1]]))

    strict = render_lenient("{{ sections.nope.rows }}", ctx, strict=True)
    lenient = render_lenient("{{ sections.nope.rows }}", ctx)

    assert not strict.ok and "nope" in (strict.error or "")
    assert "withheld" not in (strict.error or "")
    assert lenient.ok  # unchanged behaviour for the template assistant


def test_render_report_body_runs_the_template_in_the_isolated_worker() -> None:
    ctx = _context(_ok("a", [("n", "number")], [[41]]))

    body = render_report_body("Total: {{ sections.a.value + 1 }} on {{ report.name }}", ctx)

    assert body.error is None
    assert body.markdown == "Total: 42 on Fleet"


def test_render_report_body_returns_the_error_instead_of_raising() -> None:
    ctx = _context(_ok("a", [("n", "number")], [[1]]))

    syntax = render_report_body("{% for x in %}", ctx)
    undefined = render_report_body("{{ nope.x }}", ctx)
    unsafe = render_report_body("{{ ''.__class__ }}", ctx)

    for body in (syntax, undefined, unsafe):
        assert body.markdown is None and body.error


def test_markdown_in_data_cells_is_escaped_so_it_stays_text() -> None:
    columns = [ResultColumn(key="a", label="a", type="string")]

    table = markdown_table(
        columns, [["[Click](https://evil.example) # head `x` *b* _i_ <b> ![i](u) \\|"]]
    )

    cell = table.splitlines()[2]
    for raw in ("[", "]", "#", "`", "*", "_", "<", "!"):
        assert "\\" + raw in cell
    assert "\\\\\\|" in cell  # a backslash followed by a pipe: both escaped

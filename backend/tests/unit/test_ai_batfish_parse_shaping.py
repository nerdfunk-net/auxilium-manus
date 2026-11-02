"""Shaping of the Batfish parse diagnostics (fileParseStatus, parseWarning, initIssues)."""

from __future__ import annotations

from typing import Any

from services.ai_assistant.tools.batfish_shaping import shape_parse_issues

FILES: list[dict[str, Any]] = [
    {
        "File_Name": "configs/r1.cfg",
        "Status": "PASSED",
        "File_Format": "CISCO_IOS",
        "Nodes": ["r1"],
    },
    {
        "File_Name": "configs/r2.cfg",
        "Status": "PARTIALLY_UNRECOGNIZED",
        "File_Format": "CISCO_IOS",
        "Nodes": ["r2"],
    },
    {"File_Name": "configs/bad.cfg", "Status": "FAILED", "File_Format": "UNKNOWN", "Nodes": []},
]
WARNINGS: list[dict[str, Any]] = [
    {
        "Filename": "configs/r2.cfg",
        "Line": 10,
        "Text": "channel-group 1 mode on",
        "Parser_Context": "[x]",
        "Comment": "This syntax is unrecognized",
    },
    {
        "Filename": "configs/r2.cfg",
        "Line": 12,
        "Text": "channel-group 2 mode on",
        "Parser_Context": "[x]",
        "Comment": "This syntax is unrecognized",
    },
    {
        "Filename": "configs/r2.cfg",
        "Line": 40,
        "Text": "foo",
        "Parser_Context": "[y]",
        "Comment": "Unsupported feature",
    },
]
ISSUES: list[dict[str, Any]] = [
    {
        "Source_Lines": {"filename": "configs/r2.cfg", "lines": [3, 4]},
        "Type": "Convert warning (redflag)",
        "Details": "Interface Port-channel1 has no members",
    }
]


def _shape(**overrides: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    args: dict[str, Any] = {
        "file_status": FILES,
        "warnings": WARNINGS,
        "issues": ISSUES,
        "section": "all",
        "include_passed": False,
        "include_text": True,
    }
    args.update(overrides)
    return shape_parse_issues(**args)


def test_summary_counts_every_file_and_row() -> None:
    _, summary = _shape()

    assert summary["files_total"] == 3
    assert summary["files_by_status"] == {"PASSED": 1, "PARTIALLY_UNRECOGNIZED": 1, "FAILED": 1}
    assert summary["warnings_total"] == 3
    assert summary["issues_total"] == 1


def test_passed_files_are_left_out_unless_asked_for() -> None:
    rows, _ = _shape()
    files = [r for r in rows if r["Section"] == "file"]

    assert {r["File_Name"] for r in files} == {"configs/r2.cfg", "configs/bad.cfg"}

    rows, _ = _shape(include_passed=True)
    assert "configs/r1.cfg" in {r["File_Name"] for r in rows if r["Section"] == "file"}


def test_warnings_are_grouped_by_file_and_message_with_a_count() -> None:
    rows, _ = _shape()
    warnings = [r for r in rows if r["Section"] == "warning"]

    unrecognized = next(r for r in warnings if r["Message"] == "This syntax is unrecognized")
    assert unrecognized["Count"] == 2
    assert unrecognized["Line"] == [10, 12]
    assert unrecognized["Nodes"] == ["r2"]
    assert len(warnings) == 2


def test_config_text_only_with_the_content_opt_in() -> None:
    rows, _ = _shape(include_text=False)

    assert all("Text" not in r for r in rows)
    issue = next(r for r in rows if r["Section"] == "issue")
    assert "Message" not in issue
    assert issue["Status"] == "Convert warning (redflag)"
    assert issue["Line"] == [3, 4]

    rows, _ = _shape(include_text=True)
    assert next(r for r in rows if r["Section"] == "issue")["Message"].startswith("Interface")
    assert any(r.get("Text") == "channel-group 1 mode on" for r in rows)


def test_section_filter_keeps_the_summary_whole() -> None:
    rows, summary = _shape(section="warnings")

    assert {r["Section"] for r in rows} == {"warning"}
    assert summary["issues_total"] == 1


def test_lines_per_group_are_bounded() -> None:
    many = [{"Filename": "f", "Line": n, "Text": "x", "Comment": "same"} for n in range(1, 40)]
    rows, _ = _shape(file_status=[], warnings=many, issues=[])

    assert rows[0]["Count"] == 39
    assert len(rows[0]["Line"]) <= 10


def test_missing_columns_and_empty_input_do_not_fail() -> None:
    rows, summary = _shape(
        file_status=[{"Status": "FAILED"}], warnings=[{"Comment": "c"}], issues=[{}]
    )

    assert rows
    assert summary["files_total"] == 1

    rows, summary = _shape(file_status=[], warnings=[], issues=[])
    assert rows == []
    assert summary["files_total"] == 0


def test_input_is_not_mutated() -> None:
    before = [dict(w) for w in WARNINGS]
    _shape()

    assert WARNINGS == before

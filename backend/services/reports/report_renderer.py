"""Render a report snapshot to Markdown through a Jinja2 template (doc/REPORTS.md).

The template is a stored template of category ``report`` (or ``DEFAULT_TEMPLATE``). It is rendered
once per generated snapshot, in the same killable child process the template assistant uses (a
user-written template must not be able to hang or exhaust the server), with strict undefined
handling so a typo in a variable name is an error instead of silent empty text.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from models.report_definitions import SnapshotSection
from models.reports import ResultColumn
from services.ai_assistant.render_isolated import render_isolated

# What the Jinja2 template can use is documented in doc/REPORTS.md ("Report templates").
DEFAULT_TEMPLATE = """\
# {{ report.name }}
{% if report.description %}

{{ report.description }}
{% endif %}
{% for s in section_list %}

## {{ s.title }}
{% if s.text %}

{{ s.text }}
{% endif %}
{% if s.status == "error" %}

> This section could not be generated: {{ s.error }}
{% else %}

{{ s.table }}
{% endif %}
{% endfor %}
"""

RENDER_TIMEOUT_SECONDS = 5.0
# A snapshot stores its rendered text for good, so wait for a free render slot rather than fail.
RENDER_WAIT_SECONDS = 20.0
_TIMEOUT_ERROR = "Rendering the report template took too long and was stopped"


@dataclass(frozen=True)
class BodyOutcome:
    """The rendered Markdown, or why there is none."""

    markdown: str | None = None
    error: str | None = None


# Characters that start Markdown structure. Data values are untrusted (device output, free text):
# escaped, they stay visible text instead of becoming links, headings, images or emphasis.
_MARKDOWN_SPECIAL = re.compile(r"([\\|\[\]`*_<>!#~])")


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).replace("\r", " ").replace("\n", " ")
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


def markdown_table(columns: Sequence[ResultColumn], rows: Sequence[Sequence[Any]]) -> str:
    """A GitHub-style Markdown table; ``|`` and line breaks in cells are escaped."""
    if not columns or not rows:
        return "_No rows._"
    header = "| " + " | ".join(_cell(c.label) for c in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def _first_number(columns: Sequence[ResultColumn], row: Sequence[Any] | None) -> Any:
    if row is None:
        return None
    for index, column in enumerate(columns):
        value = row[index] if index < len(row) else None
        if (
            column.type == "number"
            and isinstance(value, int | float)
            and not isinstance(value, bool)
            and (not isinstance(value, float) or math.isfinite(value))
        ):
            return value
    return None


def _section_context(entry: SnapshotSection) -> dict[str, Any]:
    section = entry.section
    result = entry.result
    columns = result.columns if result is not None else []
    raw_rows = result.rows if result is not None else []
    keys = [c.key for c in columns]
    rows = [dict(zip(keys, row, strict=False)) for row in raw_rows]
    return {
        "id": section.id,
        "title": section.title,
        "text": section.text or "",
        "presentation": section.presentation,
        "status": entry.status,
        "error": entry.error,
        "columns": [c.model_dump() for c in columns],
        "rows": rows,
        "row_count": len(rows),
        "truncated": entry.truncated,
        "first": rows[0] if rows else None,
        "value": _first_number(columns, raw_rows[0] if raw_rows else None),
        "table": markdown_table(columns, raw_rows) if entry.status == "ok" else "",
    }


def build_render_context(
    *,
    name: str,
    description: str | None,
    generated_at: datetime,
    generated_by: str | None,
    sections: Sequence[SnapshotSection],
) -> dict[str, Any]:
    """Variables of a report template: ``report``, ``sections`` (by id) and ``section_list``."""
    section_list = [_section_context(entry) for entry in sections]
    return {
        "report": {
            "name": name,
            "description": description,
            "generated_at": generated_at.isoformat(),
            "generated_by": generated_by,
        },
        "sections": {s["id"]: s for s in section_list},
        "section_list": section_list,
    }


def render_report_body(template_content: str, context: dict[str, Any]) -> BodyOutcome:
    """Render synchronously (the report service runs in a worker thread, without a running loop).

    Never raises for a template problem: the snapshot is still stored, with the error."""
    try:
        outcome = asyncio.run(
            render_isolated(
                template_content,
                context,
                timeout=RENDER_TIMEOUT_SECONDS,
                strict=True,
                wait_seconds=RENDER_WAIT_SECONDS,
            )
        )
    except TimeoutError:
        return BodyOutcome(error=_TIMEOUT_ERROR)
    if not outcome.ok:
        line = f" (line {outcome.error_line})" if outcome.error_line else ""
        return BodyOutcome(error=f"{outcome.error or 'render failed'}{line}")
    return BodyOutcome(markdown=outcome.output)

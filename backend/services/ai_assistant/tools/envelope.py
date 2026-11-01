"""Standard result envelope for tools that return tables (doc/AI_TOOL_CHAIN.md §10a, §15.2).

Every table-returning tool answers with the same shape, so the model always sees whether data was
cut and by how much::

    {"rows": [...], "total_rows": 214, "total_rows_exact": true, "truncated": true,
     "handle": "res_8f3a"}

The preview size is a constant, never a tool parameter (§12.6 rule 2): a model cannot ask for an
unbounded answer. Large results are meant to be stored behind a ``handle`` (§6.1, built in the
next step); this module only carries the handle field and does not store anything.

Pure functions and frozen data: nothing here mutates its input, touches the network or checks
rights. Rights, data class and redaction stay in the choke point (``tools/base.py``).
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from services.ai_assistant.redaction import Redactor
from services.ai_assistant.tools.base import MAX_TOOL_OUTPUT_CHARS, ToolOutput

# Rows of a result that go into the prompt. Everything beyond is reachable through a handle.
PREVIEW_ROWS = 20

# Room left for the keys around the rows. The choke point cuts anything longer than
# MAX_TOOL_OUTPUT_CHARS at a character boundary, which would hand the model invalid JSON, so the
# envelope drops whole rows until it fits instead.
OUTPUT_BUDGET_CHARS = MAX_TOOL_OUTPUT_CHARS - 500

_STANDARD_KEYS = frozenset(
    {"rows", "total_rows", "total_rows_exact", "truncated", "handle", "note"}
)


@dataclass(frozen=True)
class ResultEnvelope:
    rows: list[dict[str, Any]]
    # Rows in the whole result. A lower bound when ``total_rows_exact`` is False.
    total_rows: int
    truncated: bool
    # False when the source was already cut upstream (for example by the Batfish preview cap), so
    # ``total_rows`` only says "at least this many".
    total_rows_exact: bool = True
    handle: str | None = None
    # A sentence for the model about how the result was produced or cut.
    note: str | None = None

    def with_handle(self, handle: str) -> ResultEnvelope:
        return replace(self, handle=handle)

    def with_note(self, note: str) -> ResultEnvelope:
        """A copy with ``note`` added after any existing note."""
        return replace(self, note=f"{self.note} {note}" if self.note else note)


def build_envelope(
    rows: Iterable[Mapping[str, Any]],
    *,
    max_rows: int = PREVIEW_ROWS,
    source_truncated: bool = False,
) -> ResultEnvelope:
    """Cut ``rows`` to the preview size and describe what was left out.

    ``max_rows`` may lower the preview but never raise it above ``PREVIEW_ROWS``.
    ``source_truncated`` says the caller's data is itself a prefix of a bigger result.
    """
    all_rows = [dict(row) for row in rows]
    limit = max(0, min(max_rows, PREVIEW_ROWS))
    return ResultEnvelope(
        rows=all_rows[:limit],
        total_rows=len(all_rows),
        truncated=source_truncated or len(all_rows) > limit,
        total_rows_exact=not source_truncated,
    )


def drop_columns(
    rows: Iterable[Mapping[str, Any]], columns: Collection[str]
) -> list[dict[str, Any]]:
    """Copy ``rows`` without the named columns (deprecated or redundant fields, §15.2 item 3)."""
    return [{k: v for k, v in row.items() if k not in columns} for row in rows]


def redact_envelope(envelope: ResultEnvelope, redactor: Redactor) -> ResultEnvelope:
    """Redact the preview rows *as data*, before they are JSON-encoded.

    The choke point redacts the finished string, but JSON turns a newline into the two characters
    ``\\n``, so line-anchored secret patterns (``enable secret``, ``key 7``) stop matching in a
    multi-line cell. Redacting the values first keeps real newlines in front of the patterns.
    Returns a new envelope; call it on the preview rows only, not on a whole stored table.
    """
    return replace(envelope, rows=redactor.redact_data(envelope.rows))


def envelope_output(
    envelope: ResultEnvelope, *, extra: Mapping[str, Any] | None = None
) -> ToolOutput:
    """Serialise an envelope as the tool result. ``extra`` adds tool-specific context (such as the
    snapshot used) beside the standard keys and may not replace them."""
    if extra and _STANDARD_KEYS & extra.keys():
        raise ValueError("extra may not redefine the standard envelope keys")
    rows = envelope.rows
    while True:
        payload = _payload(envelope, rows, extra)
        text = _dumps(payload)
        if len(text) <= OUTPUT_BUDGET_CHARS or not rows:
            break
        rows = rows[:-1]
    if len(rows) < len(envelope.rows):
        payload["truncated"] = True
        shrunk = _shortened_note(len(rows), len(envelope.rows), extra)
        payload["note"] = f"{envelope.note} {shrunk}" if envelope.note else shrunk
        text = _dumps(payload)
    return ToolOutput(content=text, truncated=bool(payload["truncated"]))


def _payload(
    envelope: ResultEnvelope, rows: list[dict[str, Any]], extra: Mapping[str, Any] | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "rows": rows,
        "total_rows": envelope.total_rows,
        "total_rows_exact": envelope.total_rows_exact,
        "truncated": envelope.truncated,
    }
    if envelope.handle is not None:
        payload["handle"] = envelope.handle
    if envelope.note:
        payload["note"] = envelope.note
    if extra:
        payload.update(extra)
    return payload


def _shortened_note(shown: int, wanted: int, extra: Mapping[str, Any] | None) -> str:
    if shown == 0:
        return (
            "A single row is larger than the output limit, so no row is shown. Call query_result "
            "with 'fields' to select only the columns you need."
        )
    offset = int((extra or {}).get("offset", 0))
    return (
        f"Only {shown} of {wanted} rows fit the output limit. "
        f"Continue with offset={offset + shown}, or use 'fields' to select fewer columns."
    )


def _json_default(value: Any) -> Any:
    # Sets have no order of their own; sort so the output is stable. Anything else becomes text.
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    return str(value)


def _dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, default=_json_default, ensure_ascii=False, indent=1)

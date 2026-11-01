"""Publish a table to the model: a bounded preview, plus a handle for the rest.

Shared by every tool that returns a table (doc/AI_TOOL_CHAIN.md §6.1, §10a): the preview rows go
into the prompt, the whole table goes into the ``ResultStore`` and is reachable with
``query_result`` / ``fetch_slice``. Redaction of the preview happens here, as data, before the
rows are JSON-encoded (see ``redact_envelope``).

If the store is missing, unreachable or the table is too big for it, the tool still answers with
the preview and says the rest was not stored: a storage problem must not make a query fail.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from services.ai_assistant.data_sharing import DataClass
from services.ai_assistant.results.store import (
    ResultStore,
    ResultStoreUnavailableError,
    StoredResult,
)
from services.ai_assistant.tools.base import ToolContext, ToolOutput
from services.ai_assistant.tools.envelope import (
    PREVIEW_ROWS,
    ResultEnvelope,
    build_envelope,
    envelope_output,
    redact_envelope,
)
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY

logger = logging.getLogger(__name__)

# Character budget for redacting the copy that goes to the store (it lives for hours, so it is
# stored redacted, like the preview). Separate from the request's own budget.
STORED_REDACT_CHARS = 2_000_000
# How often an over-size table is halved before giving up on storing it.
_MAX_HALVINGS = 4
_NOT_STORED = (
    "Only the preview is shown; the full result could not be stored, so query_result and "
    "fetch_slice are not available for it. Narrow the request (nodes, prefix, filters) instead."
)


async def publish_table(
    ctx: ToolContext,
    rows: list[dict[str, Any]],
    *,
    kind: str,
    data_class: DataClass,
    source_truncated: bool = False,
    note: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> ToolOutput:
    """The tool result for ``rows``: envelope, handle (when more than a preview) and redaction.

    ``source_truncated`` says ``rows`` is itself a prefix of a larger answer (the Batfish preview
    cap); the total is then reported as a lower bound. ``note`` is a sentence for the model that
    goes into the result (for example how the rows were condensed).
    """
    envelope = build_envelope(rows, source_truncated=source_truncated)
    if note:
        envelope = envelope.with_note(note)
    if len(rows) > PREVIEW_ROWS:
        envelope = await _attach_handle(
            ctx, envelope, rows, kind, data_class, source_truncated=source_truncated
        )
    envelope = await asyncio.to_thread(redact_envelope, envelope, ctx.redactor)
    return envelope_output(envelope, extra=extra)


async def _attach_handle(
    ctx: ToolContext,
    envelope: ResultEnvelope,
    rows: list[dict[str, Any]],
    kind: str,
    data_class: DataClass,
    *,
    source_truncated: bool,
) -> ResultEnvelope:
    store = ctx.extras.get(RESULT_STORE_KEY)
    if not isinstance(store, ResultStore):
        return envelope.with_note(_NOT_STORED)
    keep = rows
    for _ in range(_MAX_HALVINGS + 1):
        try:
            # The stored copy is redacted like the preview: it lives for hours.
            stored_rows = await asyncio.to_thread(
                ctx.redactor.fork(max_chars=STORED_REDACT_CHARS).redact_data, keep
            )
            handle = await store.put(
                ctx.user_id,
                StoredResult(
                    kind=kind,
                    data_class=data_class,
                    rows=stored_rows,
                    partial=source_truncated or len(keep) < len(rows),
                ),
            )
        except ValueError:
            # Too large for one handle, or too much text to redact (``RedactionBudgetExceeded``
            # is a ``ValueError``): store a prefix.
            keep = keep[: len(keep) // 2]
            if not keep:
                break
            continue
        except ResultStoreUnavailableError:
            logger.warning("Result store unavailable; returning a preview without a handle")
            return envelope.with_note(_NOT_STORED)
        envelope = envelope.with_handle(handle)
        if len(keep) < len(rows):
            return envelope.with_note(
                f"The handle holds only the first {len(keep)} of {len(rows)} rows (size limit)."
            )
        return envelope
    return envelope.with_note(_NOT_STORED)

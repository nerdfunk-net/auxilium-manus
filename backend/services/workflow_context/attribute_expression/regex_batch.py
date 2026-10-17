"""Answer the regex questions an expression pass collected, in the isolated regex runner.

A caller-supplied pattern must never run inside the API/worker process (catastrophic
backtracking holds the GIL), so every ``matches()``/``find()`` goes through
``core.regex_isolated`` — in batches, because each batch costs one child process.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from core.regex_isolated import run_regex
from services.workflow_context.attribute_expression.evaluator import (
    REGEX_INVALID,
    REGEX_STOPPED,
    RegexKey,
)

logger = logging.getLogger(__name__)

# The worker has a 2 s CPU budget per process; a small batch keeps one slow pattern from
# taking every other answer down with it.
BATCH_SIZE = 500


async def resolve_regex_batch(pending: Iterable[RegexKey]) -> dict[RegexKey, bool | str]:
    """Return ``{(text, pattern, mode): True | False | "invalid" | "stopped"}``.

    A bad or slow pattern only spoils its own answer. ``ValueError`` means the runner itself
    failed (busy, killed); its message is generic and never contains a pattern.
    """
    keys = sorted(set(pending))
    results: dict[RegexKey, bool | str] = {}
    for start in range(0, len(keys), BATCH_SIZE):
        chunk = keys[start : start + BATCH_SIZE]
        outcome = await run_regex(
            {
                "op": "match_many",
                "items": [{"text": t, "pattern": p, "mode": m} for t, p, m in chunk],
            }
        )
        if (
            not outcome.ok
            or not isinstance(outcome.result, list)
            or len(outcome.result) != len(chunk)
        ):
            logger.warning("regex batch failed: %s", outcome.error)
            raise ValueError(outcome.error or "the regular expression runner returned no result")
        for key, answer in zip(chunk, outcome.result, strict=True):
            results[key] = (
                answer if isinstance(answer, bool) or answer == REGEX_INVALID else REGEX_STOPPED
            )
    return results

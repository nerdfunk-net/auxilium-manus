"""Search texts with author-written patterns in the isolated regex worker (W6-11, W10-06).

``re`` holds the GIL while it matches, so a pattern such as ``(a+)+$`` would stall every other
step of the worker. The questions go to ``core.regex_isolated`` in batches (one child process per
batch, with a time limit per pattern); a pattern that is bad or too slow only spoils its own
answer.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from core.regex_isolated import run_regex

logger = logging.getLogger(__name__)

# One child process must finish a batch inside its 1.5 s budget, and the request travels as JSON.
MAX_ITEMS_PER_BATCH = 50
MAX_BYTES_PER_BATCH = 4_000_000

Status = Literal["match", "nomatch", "invalid", "stopped"]


@dataclass(frozen=True)
class RegexQuestion:
    text: str
    pattern: str


@dataclass(frozen=True)
class RegexAnswer:
    status: Status
    match: str | None = None
    groups: tuple[str | None, ...] = ()

    @property
    def found(self) -> bool:
        return self.status == "match"


_STOPPED = RegexAnswer(status="stopped")


def _batches(questions: Sequence[RegexQuestion]) -> list[list[int]]:
    """Indexes of ``questions`` grouped so no batch is above the item or byte cap."""
    batches: list[list[int]] = []
    current: list[int] = []
    size = 0
    for index, question in enumerate(questions):
        cost = len(question.text) + len(question.pattern)
        if current and (len(current) >= MAX_ITEMS_PER_BATCH or size + cost > MAX_BYTES_PER_BATCH):
            batches.append(current)
            current, size = [], 0
        current.append(index)
        size += cost
    if current:
        batches.append(current)
    return batches


def _answer(raw: object) -> RegexAnswer:
    if not isinstance(raw, dict):
        return _STOPPED
    status = raw.get("status")
    if status not in ("match", "nomatch", "invalid", "stopped"):
        return _STOPPED
    groups = raw.get("groups") or []
    return RegexAnswer(
        status=status,
        match=raw.get("match"),
        groups=tuple(g if isinstance(g, str) else None for g in groups),
    )


async def search_many(
    questions: Sequence[RegexQuestion],
    *,
    ignore_case: bool = False,
    multiline: bool = False,
    max_text: int = 200,
) -> list[RegexAnswer]:
    """One answer per question, in order. A failed batch answers ``stopped`` for all its items."""
    answers: list[RegexAnswer] = [_STOPPED] * len(questions)
    for indexes in _batches(questions):
        outcome = await run_regex(
            {
                "op": "search_many",
                "flags": {"case_insensitive": ignore_case, "multiline": multiline},
                "max_text": max_text,
                "items": [
                    {"text": questions[i].text, "pattern": questions[i].pattern} for i in indexes
                ],
            }
        )
        if (
            not outcome.ok
            or not isinstance(outcome.result, list)
            or len(outcome.result) != len(indexes)
        ):
            logger.warning("regex search batch failed: %s", outcome.error)
            continue
        for index, raw in zip(indexes, outcome.result, strict=True):
            answers[index] = _answer(raw)
    return answers

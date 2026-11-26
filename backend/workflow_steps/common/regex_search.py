"""Search texts with author-written patterns in the isolated regex worker (W6-11, W10-06).

``re`` holds the GIL while it matches, so a pattern such as ``(a+)+$`` would stall every other
step of the worker. The questions go to ``core.regex_isolated`` in batches (one child process per
batch, with a time limit per pattern); a pattern that is bad or too slow only spoils its own
answer.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from core import isolated_process
from core.regex_isolated import run_regex
from workflow_steps.common.failure_records import REGEX_STOPPED

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


class RegexStoppedError(RuntimeError):
    """A pattern was too slow, or the worker could not answer: the result must not be guessed."""


# ``match_any`` runs inside the worker's 1.5 s batch budget: cap the texts per batch.
MAX_TEXTS_PER_ANY_BATCH = 5000


def _text_batches(texts: Sequence[str]) -> list[list[int]]:
    batches: list[list[int]] = []
    current: list[int] = []
    size = 0
    for index, text in enumerate(texts):
        cost = len(text)
        full = len(current) >= MAX_TEXTS_PER_ANY_BATCH or size + cost > MAX_BYTES_PER_BATCH
        if current and full:
            batches.append(current)
            current, size = [], 0
        current.append(index)
        size += cost
    if current:
        batches.append(current)
    return batches


async def match_any(
    texts: Sequence[str], patterns: Sequence[str], *, ignore_case: bool = False
) -> list[bool]:
    """Per text: whether any of ``patterns`` is found in it (``re.search``), in the isolated worker.

    Raises ``RegexStoppedError`` when the worker stopped a text (too slow), failed, or rejected a
    pattern: "no match" is never inferred from a failure, because the callers *remove* what matches.
    """
    found: list[bool] = [False] * len(texts)
    live = [p for p in patterns if p]
    if not live or not texts:
        return found
    for indexes in _text_batches(texts):
        outcome = await run_regex(
            {
                "op": "match_any",
                "ignore_case": ignore_case,
                "patterns": live,
                "texts": [texts[i] for i in indexes],
            }
        )
        result = outcome.result
        if (
            not outcome.ok
            or not isinstance(result, list)
            or len(result) != len(indexes)
            or not all(isinstance(r, bool) for r in result)
        ):
            logger.warning("regex match_any batch failed: %s", outcome.error)
            raise RegexStoppedError("the pattern was stopped or could not be evaluated")
        for index, answer in zip(indexes, result, strict=True):
            found[index] = answer
    return found


# --- update-content: ordered search/replace rules over one device's text --------------------

_WORKER = Path(__file__).resolve().parents[2] / "core" / "regex_worker.py"
# A device's text (before and after the rules) may be at most this many characters.
MAX_CONTENT_CHARS = 16 * 1024 * 1024


@dataclass(frozen=True)
class ReplaceRule:
    pattern: str
    replacement: str
    flags: Mapping[str, bool] = field(default_factory=dict)
    replace_all: bool = True


class ReplaceStoppedError(ValueError):
    """The rules were stopped (time or memory) or the text is above ``MAX_CONTENT_CHARS``.

    A ``ValueError``: the sentence is written here and is safe to store on the device."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.failure = REGEX_STOPPED


def _too_large() -> ReplaceStoppedError:
    return ReplaceStoppedError(f"the content is larger than {MAX_CONTENT_CHARS} characters")


async def replace_many(text: str, rules: Sequence[ReplaceRule]) -> tuple[str, list[int]]:
    """Apply ``rules`` in order to ``text`` in the isolated worker: ``(new_text, match_counts)``.

    Raises ``ReplaceStoppedError`` when the worker stopped or failed, or a text is above the cap
    (never an unchanged text in its place), and ``ValueError`` for a bad replacement template."""
    if len(text) > MAX_CONTENT_CHARS:
        raise _too_large()
    payload = json.dumps(
        {
            "op": "replace_many",
            "text": text,
            "max_chars": MAX_CONTENT_CHARS,
            "rules": [
                {
                    "pattern": rule.pattern,
                    "replacement": rule.replacement,
                    "flags": dict(rule.flags),
                    "replace_all": rule.replace_all,
                }
                for rule in rules
            ],
        }
    ).encode()
    seconds = isolated_process.STEP_CHILD_SECONDS
    async with isolated_process.STEP_CHILD_SLOTS.hold(wait_seconds=None):
        stdout = await isolated_process.run_child(
            _WORKER,
            payload,
            timeout=seconds,
            max_response_bytes=6 * MAX_CONTENT_CHARS + 1024 * 1024,
            args=(str(int(seconds)),),
        )
    return _replace_answer(stdout, len(rules))


def _replace_answer(stdout: bytes | None, rule_count: int) -> tuple[str, list[int]]:
    stopped = ReplaceStoppedError(
        "the replace rules were stopped: they used too much time or memory on this content"
    )
    if stdout is None:
        raise stopped
    try:
        data = json.loads(stdout)
        if not data["ok"]:
            raise ValueError(str(data["error"]))
        result = data["result"]
        if result.get("too_large"):
            raise _too_large()
        updated, counts = result["updated_text"], result["match_counts"]
    except KeyError, TypeError, AttributeError, json.JSONDecodeError:
        logger.warning("The regex worker returned an unusable replace result")
        raise stopped from None
    if (
        not isinstance(updated, str)
        or not isinstance(counts, list)
        or len(counts) != rule_count
        or not all(isinstance(c, int) for c in counts)
    ):
        raise stopped
    return updated, counts

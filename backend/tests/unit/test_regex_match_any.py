"""``match_any``: author patterns that remove content run in the isolated worker (S4-07)."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from core.regex_isolated import RegexOutcome, run_regex
from workflow_steps.common import regex_search
from workflow_steps.common.regex_search import RegexStoppedError, match_any

pytestmark = pytest.mark.asyncio


async def test_worker_op_answers_per_text_for_any_pattern() -> None:
    outcome = await run_regex(
        {"op": "match_any", "patterns": ["^a", "z$"], "texts": ["abc", "xyz", "mid", ""]}
    )
    assert outcome.ok
    assert outcome.result == [True, True, False, False]


async def test_worker_op_ignore_case_applies_to_every_pattern() -> None:
    sensitive = await run_regex({"op": "match_any", "patterns": ["vlan"], "texts": ["Vlan1"]})
    insensitive = await run_regex(
        {"op": "match_any", "patterns": ["vlan"], "ignore_case": True, "texts": ["Vlan1"]}
    )
    assert sensitive.result == [False]
    assert insensitive.result == [True]


async def test_worker_op_rejects_a_bad_pattern_without_echoing_it() -> None:
    outcome = await run_regex({"op": "match_any", "patterns": ["(secret"], "texts": ["x"]})
    assert not outcome.ok
    assert "secret" not in (outcome.error or "")


async def test_match_any_helper_returns_booleans_in_order() -> None:
    assert await match_any(["uptime 5", "ok", "uptime"], ["uptime"]) == [True, False, True]


async def test_match_any_without_patterns_or_texts_answers_no_match_without_a_worker() -> None:
    with patch.object(regex_search, "run_regex", side_effect=AssertionError("worker started")):
        assert await match_any(["a"], []) == [False]
        assert await match_any(["a"], [""]) == [False]
        assert await match_any([], ["a"]) == []


async def test_match_any_splits_large_inputs_into_batches() -> None:
    calls: list[int] = []

    async def fake(request: dict, **kwargs: object) -> RegexOutcome:
        calls.append(len(request["texts"]))
        return RegexOutcome(ok=True, result=[t == "hit" for t in request["texts"]])

    texts = [
        "hit" if i % 2 == 0 else "miss" for i in range(regex_search.MAX_TEXTS_PER_ANY_BATCH + 3)
    ]
    with patch.object(regex_search, "run_regex", fake):
        answers = await match_any(texts, ["x"])

    assert calls == [regex_search.MAX_TEXTS_PER_ANY_BATCH, 3]
    assert answers == [t == "hit" for t in texts]


async def test_match_any_splits_by_bytes() -> None:
    calls: list[int] = []

    async def fake(request: dict, **kwargs: object) -> RegexOutcome:
        calls.append(len(request["texts"]))
        return RegexOutcome(ok=True, result=[False] * len(request["texts"]))

    big = "x" * (regex_search.MAX_BYTES_PER_BATCH // 2 + 1)
    with patch.object(regex_search, "run_regex", fake):
        await match_any([big, big, "y"], ["x"])

    assert calls == [1, 2]


@pytest.mark.parametrize(
    "outcome",
    [
        RegexOutcome(ok=False, error="boom"),
        RegexOutcome(ok=True, result="nope"),
        RegexOutcome(ok=True, result=[True]),  # wrong length
        RegexOutcome(ok=True, result=[True, "stopped"]),
    ],
)
async def test_match_any_fails_closed_on_every_kind_of_worker_failure(
    outcome: RegexOutcome,
) -> None:
    async def fake(request: dict, **kwargs: object) -> RegexOutcome:
        return outcome

    with patch.object(regex_search, "run_regex", fake):
        with pytest.raises(RegexStoppedError):
            await match_any(["a", "b"], ["x"])


async def test_a_catastrophic_pattern_is_stopped_not_taken_for_no_match() -> None:
    started = time.monotonic()
    with pytest.raises(RegexStoppedError):
        await match_any(["a" * 40 + "!", "sw1"], [r"(a+)+$"])
    assert time.monotonic() - started < 3


async def test_worker_op_ignores_an_empty_pattern_instead_of_matching_everything() -> None:
    outcome = await run_regex({"op": "match_any", "patterns": ["", "zzz"], "texts": ["abc"]})
    assert outcome.result == [False]


async def test_worker_op_error_is_a_fixed_sentence() -> None:
    outcome = await run_regex({"op": "match_any", "patterns": ["("], "texts": ["x"]})
    assert outcome.error == "invalid pattern"


async def test_match_any_sends_the_flag_and_only_the_non_empty_patterns() -> None:
    sent: list[dict] = []

    async def fake(request: dict, **kwargs: object) -> RegexOutcome:
        sent.append(request)
        return RegexOutcome(ok=True, result=[False])

    with patch.object(regex_search, "run_regex", fake):
        await match_any(["a"], ["", "x"], ignore_case=True)
        await match_any(["a"], ["y"])

    assert (sent[0]["op"], sent[0]["ignore_case"], sent[0]["patterns"]) == (
        "match_any",
        True,
        ["x"],
    )
    assert sent[1]["ignore_case"] is False

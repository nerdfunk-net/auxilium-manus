"""``search_many``: author regexes run in the isolated worker, in size-capped batches (W6-11)."""

from __future__ import annotations

import time

import pytest

from core.regex_isolated import run_regex
from workflow_steps.common import regex_search
from workflow_steps.common.regex_search import RegexQuestion, search_many

pytestmark = pytest.mark.asyncio


async def test_worker_op_answers_match_nomatch_invalid_and_groups() -> None:
    outcome = await run_regex(
        {
            "op": "search_many",
            "flags": {"case_insensitive": True},
            "max_text": 5,
            "items": [
                {"text": "LAB:2.local", "pattern": r":(\d+)"},
                {"text": "nothing", "pattern": r":(\d+)"},
                {"text": "x", "pattern": "("},
                {"text": "x", "pattern": ""},
                {"text": "ABCDEFGHIJ", "pattern": "abcdefgh"},
            ],
        }
    )
    assert outcome.ok
    first, second, third, fourth, fifth = outcome.result
    assert first == {"status": "match", "match": ":2", "groups": ["2"]}
    assert second["status"] == "nomatch"
    assert third["status"] == "invalid"
    assert fourth["status"] == "invalid"
    assert fifth["match"] == "ABCDE"  # cut to max_text, flags honoured


async def test_worker_op_multiline_flag() -> None:
    outcome = await run_regex(
        {
            "op": "search_many",
            "flags": {"multiline": True},
            "items": [{"text": "a\nb\n", "pattern": "^b$"}],
        }
    )
    assert outcome.result[0]["status"] == "match"


async def test_a_catastrophic_pattern_is_stopped_and_spoils_only_its_own_answer() -> None:
    started = time.monotonic()
    answers = await search_many(
        [
            RegexQuestion(text="a" * 40 + "!", pattern=r"(a+)+$"),
            RegexQuestion(text="sw12", pattern=r"sw(\d+)"),
        ]
    )
    assert time.monotonic() - started < 3
    assert answers[0].status == "stopped"
    assert answers[1].status == "match"
    assert answers[1].groups == ("12",)


async def test_empty_input_spawns_nothing() -> None:
    assert await search_many([]) == []


async def test_answers_keep_the_order_of_the_questions_across_batches(monkeypatch) -> None:
    monkeypatch.setattr(regex_search, "MAX_ITEMS_PER_BATCH", 2)
    questions = [RegexQuestion(text=f"n{i}", pattern=r"n(\d)") for i in range(5)]
    answers = await search_many(questions)
    assert [a.groups for a in answers] == [(str(i),) for i in range(5)]


async def test_batches_are_cut_by_size(monkeypatch) -> None:
    monkeypatch.setattr(regex_search, "MAX_BYTES_PER_BATCH", 10)
    seen: list[int] = []
    real = regex_search.run_regex

    async def counting(request, **kwargs):
        seen.append(len(request["items"]))
        return await real(request, **kwargs)

    monkeypatch.setattr(regex_search, "run_regex", counting)
    answers = await search_many([RegexQuestion(text="abcdef", pattern="c") for _ in range(3)])
    assert seen == [1, 1, 1]
    assert [a.status for a in answers] == ["match"] * 3


async def test_a_runner_failure_stops_every_answer_of_that_batch(monkeypatch) -> None:
    from core.regex_isolated import RegexOutcome

    async def broken(request, **kwargs):
        return RegexOutcome(ok=False, error="busy")

    monkeypatch.setattr(regex_search, "run_regex", broken)
    answers = await search_many([RegexQuestion(text="a", pattern="a")] * 2)
    assert [a.status for a in answers] == ["stopped", "stopped"]


async def test_a_short_answer_list_is_a_runner_failure(monkeypatch) -> None:
    from core.regex_isolated import RegexOutcome

    async def short(request, **kwargs):
        return RegexOutcome(ok=True, result=[])

    monkeypatch.setattr(regex_search, "run_regex", short)
    answers = await search_many([RegexQuestion(text="a", pattern="a")])
    assert answers[0].status == "stopped"


async def test_batches_are_cut_by_item_count(monkeypatch) -> None:
    monkeypatch.setattr(regex_search, "MAX_ITEMS_PER_BATCH", 2)
    seen: list[int] = []
    real = regex_search.run_regex

    async def counting(request, **kwargs):
        seen.append(len(request["items"]))
        return await real(request, **kwargs)

    monkeypatch.setattr(regex_search, "run_regex", counting)
    await search_many([RegexQuestion(text="a", pattern="a") for _ in range(5)])
    assert seen == [2, 2, 1]


async def test_an_unknown_or_malformed_answer_is_stopped(monkeypatch) -> None:
    from core.regex_isolated import RegexOutcome

    async def odd(request, **kwargs):
        return RegexOutcome(ok=True, result=[{"status": "weird"}, "nope", {"status": "nomatch"}])

    monkeypatch.setattr(regex_search, "run_regex", odd)
    answers = await search_many([RegexQuestion(text="a", pattern="a")] * 3)
    assert [a.status for a in answers] == ["stopped", "stopped", "nomatch"]


async def test_ignore_case_and_max_text_reach_the_worker() -> None:
    question = RegexQuestion(text="ABCDEFGH", pattern="abc(defg)")
    (sensitive,) = await search_many([question])
    (insensitive,) = await search_many([question], ignore_case=True, max_text=3)
    assert sensitive.status == "nomatch"
    assert insensitive.match == "ABC"  # the whole match is cut to max_text
    assert insensitive.groups == ("DEF",)  # and so is every group

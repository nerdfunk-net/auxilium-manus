"""The assistant's trial render runs in a killable subprocess with size and time limits (M3)."""

from __future__ import annotations

import asyncio
import time

import pytest

from services.ai_assistant import render_isolated
from services.ai_assistant.render_isolated import render_isolated as render
from services.ai_assistant.template_render import render_lenient

RUNAWAY = (
    "{% for a in range(100000) %}{% for b in range(100000) %}{% for c in range(100000) %}"
    "{{ a }}{% endfor %}{% endfor %}{% endfor %}"
)


def run(content: str, context: dict | None = None, timeout: float = 5.0):
    return asyncio.run(render(content, context or {}, timeout=timeout))


def test_a_normal_render_matches_the_in_process_result() -> None:
    content = "ntp {{ ntp }}\nhost {{ nautobot.hostname }}\n{% for i in [1,2] %}{{ i }}{% endfor %}"
    context = {"ntp": "10.0.0.1"}

    isolated = run(content, context)

    assert isolated == render_lenient(content, context)
    assert isolated.ok and "<<nautobot>>" in isolated.output
    assert "nautobot" in isolated.withheld[0]


def test_render_errors_cross_the_process_boundary() -> None:
    outcome = run("a\n{{ b ")

    assert not outcome.ok and outcome.error_line == 2


def test_a_runaway_template_is_killed_at_the_timeout_and_later_renders_still_work() -> None:
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        run(RUNAWAY, timeout=1.0)
    elapsed = time.monotonic() - started

    assert elapsed < 4.0
    assert run("still {{ 'fine' }}").output == "still fine"


@pytest.mark.parametrize(
    "content",
    [
        "{{ 'a' * 1000000000 }}",
        "{{ [0] * 1000000000 }}",
        "{{ 10 ** 1000000 }}",
        "{{ 'ab' * 100000 * 100000 }}",
    ],
)
def test_size_bombs_are_refused_by_the_sandbox(content: str) -> None:
    outcome = run(content)

    assert not outcome.ok
    assert "disallowed" in (outcome.error or "")


def test_ordinary_arithmetic_and_small_repetition_still_work() -> None:
    assert run("{{ 2 ** 10 }} {{ 'ab' * 3 }} {{ 6 * 7 }}").output == "1024 ababab 42"


def test_a_crashed_worker_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(render_isolated, "_WORKER", render_isolated._WORKER.with_name("nope.py"))

    outcome = run("x")

    assert not outcome.ok and "stopped" in (outcome.error or "")


def test_too_many_concurrent_renders_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(render_isolated, "_active", render_isolated.MAX_CONCURRENT_RENDERS)

    outcome = run("x")

    assert not outcome.ok and "busy" in (outcome.error or "")


def test_a_busy_renderer_fails_fast_by_default_and_waits_when_asked() -> None:
    async def scenario():
        render_isolated._active = render_isolated.MAX_CONCURRENT_RENDERS
        try:
            fast = await render("x", {})
            freed = asyncio.get_running_loop().call_later(
                0.3, lambda: setattr(render_isolated, "_active", 0)
            )
            waited = await render("y", {}, wait_seconds=3.0)
            freed.cancel()
            return fast, waited
        finally:
            render_isolated._active = 0

    fast, waited = asyncio.run(scenario())

    assert not fast.ok and "busy" in (fast.error or "")
    assert waited.ok and waited.output == "y"


def test_strict_mode_reports_output_that_is_too_large_instead_of_cutting_it() -> None:
    big = "{{ 'x' * 900000 }}{{ 'y' * 900000 }}"

    lenient = run(big)
    strict = asyncio.run(render(big, {}, strict=True))

    assert lenient.ok  # unchanged: the assistant's trial render is cut silently
    assert not strict.ok and "too large" in (strict.error or "")

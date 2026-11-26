"""S4-07: the workflow steps run author-written Jinja and regex replace rules in a killable child.

``render-jinja-template`` (Render Jinja Template), ``update-config-context`` (Update Config
Context), ``batfish-validate-facts`` (Validate Facts) and ``update-content`` (Update Content)
used to evaluate the author's template or regex in the Hatchet worker; an endless template or a
catastrophic pattern then held a worker thread for good. These tests run the real child process.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core import isolated_process
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from services.workflow_context.attribute_regex import apply_regex_content_replace
from services.workflow_context.jinja_sandbox import render_plain
from workflow_steps.common import jinja_render, regex_search
from workflow_steps.common.jinja_render import (
    JinjaTemplateError,
    TemplateStoppedError,
    UnsafeTemplateValueError,
    render_jinja_template,
)
from workflow_steps.common.regex_search import ReplaceRule, ReplaceStoppedError, replace_many

pytestmark = pytest.mark.asyncio

RUNAWAY = (
    "{% for a in range(100000) %}{% for b in range(100000) %}{% for c in range(100000) %}"
    "{{ a }}{% endfor %}{% endfor %}{% endfor %}"
)
CATASTROPHIC = "(a+)+$"
CATASTROPHIC_TEXT = "a" * 40 + "!"


@pytest.fixture
def short_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """One second instead of ten, so a runaway test is quick."""
    monkeypatch.setattr(isolated_process, "STEP_CHILD_SECONDS", 1.0)


# --- Jinja -------------------------------------------------------------------------------------


async def test_an_isolated_render_matches_the_in_process_core() -> None:
    template = "hostname {{ device.name }}\n{% for i in items %}item {{ i }}\n{% endfor %}"
    context = {"device": {"name": "r1"}, "items": [1, 2]}

    rendered = await render_jinja_template(template, context)

    assert rendered == render_plain(template, context, allow_multiline_values=False)["output"]
    assert rendered == "hostname r1\nitem 1\nitem 2\n"


async def test_an_undefined_name_keeps_its_kind_and_line_across_the_boundary() -> None:
    with pytest.raises(JinjaTemplateError) as caught:
        await render_jinja_template("ok\n{{ missing.value }}", {})

    assert caught.value.failure is not None
    assert caught.value.failure.kind == "undefined_variable"
    assert caught.value.failure.line == 2
    assert "Undefined template variable" in str(caught.value)


async def test_a_syntax_error_keeps_its_kind_and_line() -> None:
    with pytest.raises(JinjaTemplateError) as caught:
        await render_jinja_template("a\n{% if %}", {})

    assert caught.value.failure is not None
    assert caught.value.failure.kind == "template_syntax"
    assert caught.value.failure.line == 2


async def test_a_line_break_in_a_value_is_still_refused_by_default() -> None:
    with pytest.raises(UnsafeTemplateValueError) as caught:
        await render_jinja_template("x\n{{ v }}", {"v": "a\nshutdown"})

    assert caught.value.failure is not None
    assert caught.value.failure.kind == "unsafe_template_value"
    assert caught.value.failure.line == 2
    assert await render_jinja_template("{{ v }}", {"v": "a\nb"}, allow_multiline_values=True) == (
        "a\nb"
    )


async def test_a_runaway_template_is_stopped_and_the_next_render_works(short_limit) -> None:
    started = time.monotonic()
    with pytest.raises(TemplateStoppedError) as caught:
        await render_jinja_template(RUNAWAY, {})
    elapsed = time.monotonic() - started

    assert elapsed < 4.0
    assert caught.value.failure is not None
    assert caught.value.failure.kind == "resource_limit"
    assert caught.value.failure.phase == "render"
    assert await render_jinja_template("still {{ 'fine' }}", {}) == "still fine"


async def test_an_output_above_the_cap_is_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jinja_render, "MAX_RENDERED_CHARS", 10)

    with pytest.raises(TemplateStoppedError) as caught:
        await render_jinja_template("{{ 'x' * 11 }}", {})

    assert "larger than" in str(caught.value)
    assert await render_jinja_template("{{ 'x' * 10 }}", {}) == "x" * 10


async def test_a_context_value_that_is_not_plain_data_fails_without_a_child() -> None:
    spawn = AsyncMock()
    with (
        patch.object(isolated_process.asyncio, "create_subprocess_exec", spawn),
        pytest.raises(JinjaTemplateError) as caught,
    ):
        await render_jinja_template("{{ v }}", {"v": object()})

    spawn.assert_not_awaited()
    assert "not plain data" in str(caught.value)
    assert caught.value.failure is not None
    assert caught.value.failure.kind == "template_error"


async def test_a_crashed_worker_is_a_stop_not_a_guess(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jinja_render, "_WORKER", jinja_render._WORKER.with_name("missing.py"))

    with pytest.raises(TemplateStoppedError):
        await render_jinja_template("a", {})


async def test_the_jinja_child_gets_an_empty_environment() -> None:
    seen: dict = {}
    real = asyncio.create_subprocess_exec

    async def spy(*args, **kwargs):
        seen["env"] = kwargs.get("env")
        seen["args"] = args
        return await real(*args, **kwargs)

    with patch.object(isolated_process.asyncio, "create_subprocess_exec", spy):
        await render_jinja_template("a", {})

    assert seen["env"] == {}
    assert "-I" in seen["args"]


# --- Regex replace -----------------------------------------------------------------------------


async def test_replace_many_matches_the_in_process_rules_in_order() -> None:
    text = "interface Gi1\n description OLD\ninterface Gi2\n description old\n"
    rules = [
        ReplaceRule(pattern="old", replacement="new", flags={"case_insensitive": True}),
        ReplaceRule(pattern=r"interface (\S+)", replacement=r"intf \1", replace_all=False),
    ]

    updated, counts = await replace_many(text, rules)

    expected = text
    expected_counts = []
    for rule in rules:
        expected, count = apply_regex_content_replace(
            source_text=expected,
            pattern=rule.pattern,
            replacement=rule.replacement,
            flags=rule.flags,
            replace_all=rule.replace_all,
        )
        expected_counts.append(count)
    assert (updated, counts) == (expected, expected_counts)
    assert counts == [2, 1]


async def test_a_catastrophic_pattern_is_stopped(short_limit) -> None:
    started = time.monotonic()
    with pytest.raises(ReplaceStoppedError) as caught:
        await replace_many(CATASTROPHIC_TEXT, [ReplaceRule(pattern=CATASTROPHIC, replacement="")])

    assert time.monotonic() - started < 4.0
    assert caught.value.failure.kind == "resource_limit"
    assert caught.value.failure.phase == "config"


async def test_a_bad_replacement_template_is_a_value_error_with_its_text() -> None:
    with pytest.raises(ValueError, match="invalid replacement template") as caught:
        await replace_many("abc", [ReplaceRule(pattern="b", replacement=r"\9")])

    assert not isinstance(caught.value, ReplaceStoppedError)


async def test_content_above_the_cap_is_refused_without_a_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(regex_search, "MAX_CONTENT_CHARS", 5)
    spawn = AsyncMock()
    with (
        patch.object(isolated_process.asyncio, "create_subprocess_exec", spawn),
        pytest.raises(ReplaceStoppedError, match="larger than"),
    ):
        await replace_many("abcdef", [ReplaceRule(pattern="a", replacement="b")])

    spawn.assert_not_awaited()


async def test_a_result_above_the_cap_is_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(regex_search, "MAX_CONTENT_CHARS", 5)

    with pytest.raises(ReplaceStoppedError, match="larger than"):
        await replace_many("abc", [ReplaceRule(pattern="b", replacement="bbbb")])
    assert await replace_many("abc", [ReplaceRule(pattern="b", replacement="bbb")]) == (
        "abbbc",
        [1],
    )


# --- Slots -------------------------------------------------------------------------------------


async def test_step_children_queue_for_a_slot_instead_of_failing_busy() -> None:
    slots = isolated_process.ChildSlots(1)
    order: list[str] = []

    async def job(name: str, hold: float) -> None:
        async with slots.hold(wait_seconds=None) as got:
            assert got
            order.append(f"{name}+")
            await asyncio.sleep(hold)
            order.append(f"{name}-")

    await asyncio.gather(job("a", 0.2), job("b", 0.0))

    assert order == ["a+", "a-", "b+", "b-"]
    assert slots.active == 0


async def test_a_bounded_wait_gives_up_when_every_slot_is_held() -> None:
    slots = isolated_process.ChildSlots(1)
    async with slots.hold(wait_seconds=None):
        async with slots.hold(wait_seconds=0.1) as got:
            assert not got
    assert slots.active == 0


# --- The steps ---------------------------------------------------------------------------------


def _device(**extra) -> DeviceContext:
    return DeviceContext(
        id="d1",
        name="r1",
        hostname="r1",
        status=DeviceStatus.OK,
        capabilities={Capability.IDENTITY},
        **extra,
    )


async def test_update_content_fails_the_device_when_a_rule_is_stopped(short_limit) -> None:
    from workflow_steps.update_content.executor import execute

    artifacts = InMemoryArtifactService()
    ref = await artifacts.store(
        content=CATASTROPHIC_TEXT, kind="running_config", device_id="d1", run_id="r"
    )
    outcomes = await execute(
        config={"replace_rules": [{"pattern": CATASTROPHIC, "replacement": ""}]},
        context=WorkflowContext(
            run_id="r", workflow_id="w", devices={"d1": _device(running_config_ref=ref)}
        ),
        run=MagicMock(id=1),
        artifact_service=artifacts,
        node_id="uc-1",
        device_sessions=MagicMock(),
    )

    by_name = {o.name: o for o in outcomes}
    error = by_name["failure"].context.devices["d1"].errors[-1]
    assert error.code == "regex_stopped"
    assert error.failure is not None and error.failure.kind == "resource_limit"


async def test_render_jinja_template_fails_the_device_on_a_runaway_template(short_limit) -> None:
    from workflow_steps.render_jinja_template.executor import execute

    with patch(
        "workflow_steps.render_jinja_template.executor.load_stored_template", return_value=RUNAWAY
    ):
        outcomes = await execute(
            config={"template_id": 1, "output_key": "cfg"},
            context=WorkflowContext(run_id="r", workflow_id="w", devices={"d1": _device()}),
            run=MagicMock(id=1),
            artifact_service=InMemoryArtifactService(),
            node_id="rj-1",
            device_sessions=MagicMock(),
        )

    by_name = {o.name: o for o in outcomes}
    error = by_name["failure"].context.devices["d1"].errors[-1]
    assert error.code == "template_error"
    assert error.failure is not None and error.failure.kind == "resource_limit"


async def test_update_config_context_renders_its_value_template_isolated(short_limit) -> None:
    from workflow_steps.update_config_context import executor as mod

    source = mod._ValueSource(type="template", attribute_path="", template_id=3)
    with (
        patch.object(mod, "load_stored_template", return_value=RUNAWAY),
        pytest.raises(TemplateStoppedError),
    ):
        await mod._resolve_value(value_source=source, device=_device(), run_id="r", workflow_id="w")


async def test_validate_facts_fails_the_device_on_a_runaway_fact_template(short_limit) -> None:
    from services.batfish.credentials import BatfishConnection
    from workflow_steps.batfish_validate_facts.executor import execute
    from workflow_steps.common.batfish_context import store_batfish_snapshot

    context = store_batfish_snapshot(
        WorkflowContext(run_id="r", workflow_id="7", devices={"d1": _device()}),
        connection=BatfishConnection(host="batfish", port=9996),
        network="n",
        snapshot="s",
    )
    with patch("workflow_steps.batfish_validate_facts.executor.service_factory") as factory:
        factory.get_batfish_app_service.return_value.validate_facts = AsyncMock(return_value={})
        outcomes = await execute(
            config={"facts_source": "field", "fact_key": "Hostname", "fact_value": RUNAWAY},
            context=context,
            run=MagicMock(id=1),
            artifact_service=InMemoryArtifactService(),
            node_id="vf-1",
            device_sessions=MagicMock(),
        )

    by_name = {o.name: o for o in outcomes}
    error = by_name["failure"].context.devices["d1"].errors[-1]
    assert error.code == "render_error"
    assert error.failure is not None and error.failure.kind == "resource_limit"


async def test_the_replace_child_gets_the_step_cpu_limit() -> None:
    seen: dict = {}
    real = asyncio.create_subprocess_exec

    async def spy(*args, **kwargs):
        seen["args"] = args
        seen["env"] = kwargs.get("env")
        return await real(*args, **kwargs)

    with patch.object(isolated_process.asyncio, "create_subprocess_exec", spy):
        await replace_many("a", [ReplaceRule(pattern="a", replacement="b")])

    assert seen["args"][-1] == "10"
    assert seen["env"] == {}


@pytest.mark.parametrize(
    ("argv", "seconds"),
    [([], 2), (["10"], 10), (["0"], 1), (["99"], 30), (["ten"], 2)],
)
async def test_the_regex_worker_cpu_limit_comes_from_its_first_argument(argv, seconds) -> None:
    from core.regex_worker import _cpu_seconds

    assert _cpu_seconds(argv) == seconds


async def test_a_child_that_answers_and_then_fails_is_not_trusted(tmp_path) -> None:
    worker = tmp_path / "worker.py"
    worker.write_text("import sys\nsys.stdout.write('{\"ok\": true}')\nsys.exit(3)\n")

    assert await isolated_process.run_child(worker, b"", timeout=5, max_response_bytes=100) is None


async def test_an_answer_above_the_response_cap_is_not_trusted(tmp_path) -> None:
    worker = tmp_path / "worker.py"
    worker.write_text("import sys\nsys.stdout.write('x' * 11)\n")

    assert await isolated_process.run_child(worker, b"", timeout=5, max_response_bytes=10) is None
    assert await isolated_process.run_child(worker, b"", timeout=5, max_response_bytes=11) == (
        b"x" * 11
    )


@pytest.mark.parametrize(
    "result",
    [
        {"updated_text": "a", "match_counts": [1, 1]},
        {"updated_text": "a", "match_counts": []},
        {"updated_text": 1, "match_counts": [1]},
        {"updated_text": "a", "match_counts": ["1"]},
        {"match_counts": [1]},
    ],
)
async def test_a_malformed_replace_answer_is_a_stop(result) -> None:
    import json

    stdout = json.dumps({"ok": True, "result": result}).encode()
    with pytest.raises(ReplaceStoppedError, match="stopped"):
        regex_search._replace_answer(stdout, 1)

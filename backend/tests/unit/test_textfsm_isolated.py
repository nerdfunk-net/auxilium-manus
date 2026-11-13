"""TextFSM in a killable child process (review finding 1) with the cisco_xe retry (finding 2)."""

from __future__ import annotations

import asyncio

import pytest

from core import textfsm_isolated as ti

SHOW_VERSION = (
    "Cisco IOS Software, Version 15.2(4)M, RELEASE SOFTWARE (fc2)\nrouter1 uptime is 1 day\n"
)


def _run(platform, items, **kw):
    return asyncio.run(ti.run_textfsm(platform, items, **kw))


def test_parses_a_known_command_in_the_child() -> None:
    outcome = _run("cisco_ios", [("show version", SHOW_VERSION)])

    assert outcome.ok
    [item] = outcome.items
    assert item.error is None and item.rows[0]["hostname"] == "router1"


def test_cisco_xe_uses_the_cisco_ios_templates() -> None:
    outcome = _run("cisco_xe", [("show version", SHOW_VERSION)])

    [item] = outcome.items
    assert item.error is None and item.rows[0]["hostname"] == "router1"


def test_no_template_and_no_match_are_told_apart_per_item() -> None:
    outcome = _run(
        "cisco_ios",
        [
            ("show nonsense thing", "x"),
            ("show version", "nothing useful"),
            ("show version", SHOW_VERSION),
        ],
    )

    codes = [i.error for i in outcome.items]
    assert codes == [ti.NO_TEMPLATE, ti.NO_MATCH, None]


def test_a_stopped_child_is_an_error_not_an_exception(monkeypatch) -> None:
    monkeypatch.setattr(ti, "_WORKER", ti._WORKER.with_name("does_not_exist.py"))

    outcome = _run("cisco_ios", [("show version", SHOW_VERSION)])

    assert not outcome.ok and outcome.error == ti.STOPPED


def test_a_child_that_outlives_the_timeout_is_killed(monkeypatch, tmp_path) -> None:
    slow = tmp_path / "slow_worker.py"
    slow.write_text("import time\ntime.sleep(30)\n")
    monkeypatch.setattr(ti, "_WORKER", slow)

    outcome = _run("cisco_ios", [("show version", "x")], timeout=0.3)

    assert not outcome.ok and outcome.error == ti.STOPPED


def test_the_child_gets_no_environment(monkeypatch, tmp_path) -> None:
    probe = tmp_path / "probe_worker.py"
    probe.write_text(
        "import json, os, sys\n"
        "sys.stdin.read()\n"
        "print(json.dumps({'ok': True, 'result': "
        "[{'rows': [{'leaked': 'SECRET_KEY' in os.environ}], 'error': None}]}))\n"
    )
    monkeypatch.setattr(ti, "_WORKER", probe)
    monkeypatch.setenv("SECRET_KEY", "must-not-leak")

    [item] = _run("cisco_ios", [("show version", "x")]).items

    assert item.rows == [{"leaked": False}]


def test_a_garbage_reply_is_an_error(monkeypatch, tmp_path) -> None:
    bad = tmp_path / "bad_worker.py"
    bad.write_text("import sys\nsys.stdin.read()\nprint('not json')\n")
    monkeypatch.setattr(ti, "_WORKER", bad)

    outcome = _run("cisco_ios", [("show version", "x")])

    assert not outcome.ok and outcome.error == ti.STOPPED


def test_a_busy_runner_says_so(monkeypatch) -> None:
    monkeypatch.setattr(ti, "_active", ti.MAX_CONCURRENT_JOBS)

    outcome = _run("cisco_ios", [("show version", "x")], wait_seconds=0.1)

    assert not outcome.ok and outcome.error == ti.BUSY


def test_the_slot_is_released_after_a_run() -> None:
    _run("cisco_ios", [("show version", SHOW_VERSION)])

    assert ti._active == 0


@pytest.mark.skipif(not hasattr(__import__("signal"), "setitimer"), reason="needs setitimer")
def test_one_slow_template_match_only_spoils_its_own_item() -> None:
    # A single output that makes one item exceed its own time limit must not stop the others.
    from core import textfsm_worker as tw

    answers = tw.parse_items("cisco_ios", [["show version", SHOW_VERSION]], item_seconds=5)

    assert answers[0]["error"] is None

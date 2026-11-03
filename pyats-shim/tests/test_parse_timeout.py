"""POST /v1/parse must not block the event loop or wait forever for one slow parse.

Does not need genie: ``_parse_one`` is replaced, so this runs in every environment.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import parse as parse_module
from app.config import get_settings
from tests import TEST_TOKEN


@pytest.fixture(autouse=True)
def _shim_token(monkeypatch):
    monkeypatch.setenv("PYATS_SHIM_TOKEN", TEST_TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(parse_module.router)
    return TestClient(app)


def _body(*commands: str):
    return {
        "devices": {
            "dev1": {
                "os": "iosxe",
                "commands": [{"command": c, "output": "x"} for c in commands],
            }
        }
    }


def _post(client, *commands):
    return client.post(
        "/v1/parse",
        json=_body(*commands),
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )


def _request(*commands: str) -> parse_module.ParseRequest:
    return parse_module.ParseRequest.model_validate(_body(*commands))


async def test_a_slow_parse_is_abandoned_with_a_fixed_error_and_the_rest_still_run(
    monkeypatch,
):
    # Called as a coroutine in the test's own loop: TestClient closes its loop after each request,
    # which waits for the abandoned thread, and that would hide what this checks.
    release = threading.Event()

    def fake(*, os_name, command, output):
        if command == "slow":
            release.wait(10)
            return parse_module.ParseCommandResult(parsed={"late": True})
        return parse_module.ParseCommandResult(parsed={"ok": command})

    monkeypatch.setattr(parse_module, "_parse_one", fake)
    monkeypatch.setattr(parse_module, "PARSE_COMMAND_TIMEOUT_SECONDS", 0.2)

    started = time.monotonic()
    try:
        response = await parse_module.parse_output(_request("slow", "fast"))
    finally:
        release.set()

    assert time.monotonic() - started < 3
    commands = response.results["dev1"].commands
    assert commands["slow"].parsed is None
    assert commands["slow"].error == parse_module.PARSE_TIMED_OUT
    assert commands["fast"].parsed == {"ok": "fast"} and commands["fast"].error is None


def test_a_parse_is_not_run_on_the_event_loop_thread(client, monkeypatch):
    seen: list[str] = []

    def fake(*, os_name, command, output):
        seen.append(threading.current_thread().name)
        return parse_module.ParseCommandResult(parsed={})

    monkeypatch.setattr(parse_module, "_parse_one", fake)

    _post(client, "show version")

    assert seen and seen[0] != threading.main_thread().name


async def test_the_timeout_error_does_not_contain_the_command_output(monkeypatch):
    release = threading.Event()

    def fake(*, os_name, command, output):
        release.wait(10)
        return parse_module.ParseCommandResult(parsed={})

    monkeypatch.setattr(parse_module, "_parse_one", fake)
    monkeypatch.setattr(parse_module, "PARSE_COMMAND_TIMEOUT_SECONDS", 0.1)
    try:
        response = await parse_module.parse_output(_request("show version"))
    finally:
        release.set()

    error = response.results["dev1"].commands["show version"].error
    assert error == parse_module.PARSE_TIMED_OUT

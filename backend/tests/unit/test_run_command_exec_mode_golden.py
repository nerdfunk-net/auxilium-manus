"""run-command (Run Command) exec mode: characterization of ``run_exec_mode`` (W3a-17 layout).

Written before ``exec_mode._run_on_device`` was split into smaller helpers; it passes on the old
and the new code (a characterization test, not a regression test). It pins what the split must
keep: the per-device triple (success / failed / raw outputs), the dry-run payload, the summaries
(including a structured output that is not JSON), the TextFSM ``None`` marker for a raw-text
fallback, the stored artifacts and the per-device log lines.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from models.failure import FailureInfo
from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import CommandResult as NetmikoCommandResult
from workflow_steps.common.failure_records import INVALID_INPUT
from workflow_steps.run_command.exec_mode import run_exec_mode
from workflow_steps.run_command.parsing import parse_run_command_config

pytestmark = pytest.mark.asyncio

_FAILED = FailureInfo(phase="command", kind="command_error")
_COMMANDS = ["show version", "show ip int brief", "reload"]


def _device(device_id: str, *, host: str | None = "10.0.0.1/24", driver: str = "cisco_ios"):
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id if host else "",
        primary_ip4=host,
        network_driver=driver,
        status=DeviceStatus.OK,
    )


def _result(host: str) -> NetmikoCommandResult:
    if host == "10.0.0.3":
        return NetmikoCommandResult(success=False, output="", error="% bad", failure=_FAILED)
    if host == "10.0.0.4":
        raise ConnectionError("refused")
    return NetmikoCommandResult(
        success=True,
        output="",
        command_outputs={
            "show version": '[{"version": "17"}]',
            "show ip int brief": "not json at all",
            "reload": "raw text",
        },
        structured_commands=["show version", "show ip int brief"],
        confirmed_prompts=["reload"],
    )


def _context() -> WorkflowContext:
    return WorkflowContext(
        run_id="run-uuid",
        workflow_id="wf",
        devices={
            "ok": _device("ok", host="10.0.0.1/24"),
            "nohost": _device("nohost", host=None),
            "cli": _device("cli", host="10.0.0.3/24"),
            "boom": _device("boom", host="10.0.0.4/24"),
            "weird": _device("weird", host="10.0.0.5/24", driver="no_such_platform"),
        },
    )


def _parsed(**changes: Any):
    base = parse_run_command_config(
        {"credential_reference": "lab", "commands": _COMMANDS, "parser": "textfsm"}, None
    )
    return replace(base, **changes)


async def _call(parsed, netmiko) -> tuple[Any, Any, Any, InMemoryArtifactService]:
    artifacts = InMemoryArtifactService()
    success, failed, raw = await run_exec_mode(
        context=_context(),
        node_id="n1",
        run_id=7,
        parsed=parsed,
        username="u",
        password="p",
        netmiko=netmiko,
        artifact_service=artifacts,
    )
    return success, failed, raw, artifacts


def _netmiko() -> MagicMock:
    netmiko = MagicMock()
    netmiko.send_commands = AsyncMock(side_effect=lambda **kw: _result(kw["host"]))
    return netmiko


def _errors(device: DeviceContext) -> list[tuple[str, str, str, Any]]:
    return [(e.node_id, e.code, e.message, e.failure) for e in device.errors]


async def test_the_device_triple_and_records(caplog: pytest.LogCaptureFixture) -> None:
    netmiko = _netmiko()
    with (
        caplog.at_level(logging.INFO, logger="workflow_steps.run_command.exec_mode"),
        caplog.at_level(logging.INFO, logger="workflow_steps.common.device_runner"),
    ):
        success, failed, raw, artifacts = await _call(_parsed(), netmiko)

    assert list(success) == ["ok"]
    assert sorted(failed) == ["boom", "cli", "nohost", "weird"]
    assert raw == {
        "ok": {
            "show version": '[{"version": "17"}]',
            "show ip int brief": "not json at all",
            "reload": None,  # TextFSM raw-text fallback marker
        }
    }

    rows = success["ok"].command_results["n1"]
    assert [(r.command, r.success, r.summary) for r in rows] == [
        ("show version", True, "1 row(s) parsed"),
        ("show ip int brief", True, "15 bytes"),
        ("reload", True, "8 bytes · confirmation prompt auto-confirmed"),
    ]
    assert all(r.node_id == "n1" and r.output_ref for r in rows)
    assert success["ok"].status == DeviceStatus.OK

    assert _errors(failed["nohost"]) == [
        ("n1", "missing_host", "Device nohost has no hostname or primary IP", INVALID_INPUT)
    ]
    cli = failed["cli"]
    assert _errors(cli) == [("n1", "command_failed", "Command execution failed", _FAILED)]
    assert [r.summary for r in cli.command_results["n1"]] == ["0 bytes"] * 3
    assert [r.success for r in cli.command_results["n1"]] == [False] * 3
    assert [e.code for e in failed["boom"].errors] == ["connectionerror"]
    assert [e.code for e in failed["weird"].errors] == ["unsupportedplatformerror"]

    sent = {c.kwargs["host"]: c.kwargs for c in netmiko.send_commands.call_args_list}
    assert sorted(sent) == ["10.0.0.1", "10.0.0.3", "10.0.0.4"]
    call = sent["10.0.0.1"]
    assert (call["device_type"], call["use_textfsm"], call["commands"]) == (
        "cisco_ios",
        True,
        _COMMANDS,
    )
    assert (call["username"], call["password"], call["credential_reference"]) == ("u", "p", "lab")

    refs = [r.output_ref for d in (success["ok"], cli) for r in d.command_results["n1"]]
    # one stored artifact per command, for "ok" and for "cli"
    assert len({r.artifact_id for r in refs if r}) == 6

    messages = [r.getMessage() for r in caplog.records]
    # W3a-05: the per-device lines come from the shared runner (as config mode), with the
    # context's run id.
    run_id = _context().run_id
    assert f"run-command device 1/5 id=ok host=10.0.0.1: connecting run_id={run_id}" in messages
    assert f"run-command device 1/5 id=ok host=10.0.0.1: ok run_id={run_id}" in messages
    assert f"run-command device 2/5 id=nohost host=(no host): failed run_id={run_id}" in messages
    assert any("auto-confirmed 1 prompt(s) run_id=7 node_id=n1 device_id=ok" in m for m in messages)


async def test_dry_run_sends_nothing_and_records_the_plan() -> None:
    netmiko = _netmiko()
    success, failed, raw, _ = await _call(_parsed(dry_run=True), netmiko)

    netmiko.send_commands.assert_not_called()
    assert sorted(success) == ["boom", "cli", "ok", "weird"]
    assert list(failed) == ["nohost"]
    assert raw == {"boom": {}, "cli": {}, "ok": {}, "weird": {}}
    assert success["ok"].dry_run_results["n1"] == {
        "would_execute": True,
        "execution_mode": "exec_mode",
        "commands": _COMMANDS,
        "host": "10.0.0.1",
    }


async def test_without_textfsm_raw_outputs_are_kept() -> None:
    success, _, raw, _ = await _call(_parsed(parser_mode="none"), _netmiko())

    assert raw["ok"]["reload"] == "raw text"
    assert success["ok"].command_results["n1"][0].summary == "1 row(s) parsed"

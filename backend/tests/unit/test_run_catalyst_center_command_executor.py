"""Tests for the run-catalyst-center-command executor (mocked service layer, no network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.catalyst_center import CatalystCenterCommandResult, CatalystCenterCommandStatus
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.catalyst_center.common.exceptions import CatalystCenterAPIError
from services.catalyst_center.source_config_service import CatalystCenterSourceNotFoundError
from workflow_steps.run_catalyst_center_command.config import get_config
from workflow_steps.run_catalyst_center_command.executor import (
    DEVICES_PER_REQUEST,
    execute,
)

MODULE = "workflow_steps.run_catalyst_center_command.executor"
TARGETS = "workflow_steps.common.catalyst_center_targets"
OK = CatalystCenterCommandStatus.SUCCESS


def _device(
    device_id: str, *, source: str = "catalyst_center", source_id: str = "lab"
) -> DeviceContext:
    return DeviceContext(
        id=device_id, name=device_id, hostname=device_id, source=source, source_id=source_id
    )


def _context(*devices: DeviceContext) -> WorkflowContext:
    return WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={d.id: d for d in devices})


def _result(device_id: str, command: str, output: str, status=OK) -> CatalystCenterCommandResult:
    return CatalystCenterCommandResult(
        device_id=device_id, command=command, status=status, output=output
    )


class _Harness:
    def __init__(self, run_commands=None, resolve_side_effect=None):
        self.command_service = MagicMock()
        self.command_service.run_commands = run_commands or AsyncMock(return_value=())
        self.source_config = MagicMock()
        self.source_config.resolve_credentials.side_effect = resolve_side_effect or (
            lambda source_id: MagicMock(name=f"creds-{source_id}")
        )
        self.build_command_service = MagicMock(return_value=self.command_service)

    def __enter__(self):
        self._patches = [
            patch(f"{MODULE}.object_session", return_value=MagicMock()),
            patch(
                "service_factory.build_catalyst_center_source_config_service",
                return_value=self.source_config,
            ),
            patch(
                "service_factory.build_catalyst_center_command_service", self.build_command_service
            ),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


async def _run(config: dict, context: WorkflowContext, artifacts=None):
    run = MagicMock()
    run.id = 1
    return await execute(
        config=config,
        context=context,
        run=run,
        artifact_service=artifacts or InMemoryArtifactService(),
        node_id="node-1",
        device_sessions=MagicMock(),
    )


class ConfigValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_config_raises_before_any_io(self) -> None:
        bad = [
            {"commands": []},
            {"commands": "show version"},
            {"commands": ["show version", "show version"]},
            {"commands": ["show version"], "timeout": 0},
            {"commands": ["show version"], "timeout": 301},
            {"commands": ["show version"], "timeout": True},
            {"commands": [f"show {i}" for i in range(21)]},
        ]
        for config in bad:
            with self.subTest(config=config), _Harness() as h:
                with self.assertRaises(ValueError):
                    await _run(config, _context(_device("a")))
                h.source_config.resolve_credentials.assert_not_called()

    async def test_unknown_source_is_a_value_error(self) -> None:
        with _Harness(resolve_side_effect=CatalystCenterSourceNotFoundError("lab")):
            with self.assertRaisesRegex(ValueError, "'lab' not found"):
                await _run(get_config(), _context(_device("a")))

    async def test_no_devices_is_a_noop_success(self) -> None:
        with _Harness() as h:
            outcomes = await _run(get_config(), _context())
        self.assertEqual([o.name for o in outcomes], ["success"])
        h.build_command_service.assert_not_called()


class SuccessPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_stores_cleaned_output_per_command(self) -> None:
        artifacts = InMemoryArtifactService()
        run_commands = AsyncMock(
            return_value=(_result("a", "show clock", "show clock\n15:22:13\nsw1#"),)
        )
        with _Harness(run_commands):
            outcomes = await _run({"commands": ["show clock"]}, _context(_device("a")), artifacts)

        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["a"]
        self.assertEqual(device.status, DeviceStatus.OK)
        (command_result,) = device.command_results["node-1"]
        self.assertTrue(command_result.success)
        self.assertEqual(await artifacts.resolve(command_result.output_ref), "15:22:13")
        self.assertIn("1 line(s)", command_result.summary)
        run_commands.assert_awaited_once_with(["a"], ["show clock"], timeout=300)

    async def test_devices_are_batched_per_request(self) -> None:
        devices = [_device(f"d{i}") for i in range(DEVICES_PER_REQUEST + 1)]
        run_commands = AsyncMock(
            side_effect=lambda ids, cmds, timeout: tuple(_result(i, cmds[0], "ok") for i in ids)
        )
        with _Harness(run_commands):
            outcomes = await _run({"commands": ["show x"]}, _context(*devices))

        self.assertEqual(run_commands.await_count, 2)
        self.assertEqual(len(outcomes[0].context.devices), DEVICES_PER_REQUEST + 1)
        self.assertEqual([o.name for o in outcomes], ["success"])

    async def test_each_source_resolves_its_own_credentials(self) -> None:
        run_commands = AsyncMock(
            side_effect=lambda ids, cmds, timeout: tuple(_result(i, cmds[0], "ok") for i in ids)
        )
        with _Harness(run_commands) as h:
            await _run(
                {"commands": ["show x"]},
                _context(_device("a", source_id="one"), _device("b", source_id="two")),
            )
        resolved = {c.args[0] for c in h.source_config.resolve_credentials.call_args_list}
        self.assertEqual(resolved, {"one", "two"})


class FailurePathTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_catalyst_device_fails_without_a_request(self) -> None:
        with _Harness() as h:
            outcomes = await _run(
                get_config(), _context(_device("n1", source="nautobot", source_id="nb"))
            )
        failure = next(o for o in outcomes if o.name == "failure")
        self.assertEqual(failure.context.devices["n1"].errors[0].code, "not_catalyst_center_device")
        h.command_service.run_commands.assert_not_awaited()

    async def test_blocklisted_command_fails_the_device_but_keeps_results(self) -> None:
        run_commands = AsyncMock(
            return_value=(
                _result("a", "show clock", "ok"),
                _result("a", "reload", "", CatalystCenterCommandStatus.BLOCKLISTED),
            )
        )
        with _Harness(run_commands):
            outcomes = await _run({"commands": ["show clock", "reload"]}, _context(_device("a")))

        failure = next(o for o in outcomes if o.name == "failure")
        device = failure.context.devices["a"]
        self.assertEqual(device.errors[0].code, "command_failed")
        self.assertIn("reload", device.errors[0].message)
        self.assertEqual([r.success for r in device.command_results["node-1"]], [True, False])

    async def test_missing_device_output_is_a_failure(self) -> None:
        with _Harness(AsyncMock(return_value=(_result("a", "show x", "ok"),))):
            outcomes = await _run({"commands": ["show x"]}, _context(_device("a"), _device("b")))
        self.assertEqual(
            set(next(o for o in outcomes if o.name == "success").context.devices), {"a"}
        )
        self.assertEqual(
            set(next(o for o in outcomes if o.name == "failure").context.devices), {"b"}
        )

    async def test_controller_error_fails_the_batch_not_the_step(self) -> None:
        with _Harness(AsyncMock(side_effect=CatalystCenterAPIError("boom"))):
            outcomes = await _run({"commands": ["show x"]}, _context(_device("a")))
        failure = next(o for o in outcomes if o.name == "failure")
        self.assertEqual(failure.context.devices["a"].errors[0].code, "catalyst_center_error")
        self.assertEqual(failure.context.devices["a"].status, DeviceStatus.FAILED)


IP_BRIEF = (
    "show ip interface brief\n"
    "Interface              IP-Address      OK? Method Status                Protocol\n"
    "Vlan1                  unassigned      YES unset  up                    up\n"
    "Gi1/0/1                10.1.1.1        YES manual up                    up\n"
    "sw1#"
)


def _driver_device(device_id: str, driver: str | None = "cisco_xe") -> DeviceContext:
    return _device(device_id).model_copy(update={"network_driver": driver})


class TextFsmParserTests(unittest.IsolatedAsyncioTestCase):
    async def test_parser_none_adds_no_parsed_data(self) -> None:
        run_commands = AsyncMock(return_value=(_result("a", "show ip interface brief", IP_BRIEF),))
        with _Harness(run_commands):
            outcomes = await _run(
                {"commands": ["show ip interface brief"]}, _context(_driver_device("a"))
            )
        device = outcomes[0].context.devices["a"]
        self.assertEqual(device.parsed, {})
        self.assertNotIn(Capability.PARSED, device.capabilities)

    async def test_textfsm_lands_in_the_shared_shape(self) -> None:
        command = "show ip interface brief"
        run_commands = AsyncMock(return_value=(_result("a", command, IP_BRIEF),))
        with _Harness(run_commands):
            outcomes = await _run(
                {"commands": [command], "parser": "textfsm", "parsed_output_key": "ifaces"},
                _context(_driver_device("a")),
            )
        device = outcomes[0].context.devices["a"]
        entry = device.parsed["ifaces"][command]
        self.assertIsNone(entry["error"])
        self.assertEqual([row["interface"] for row in entry["parsed"]], ["Vlan1", "Gi1/0/1"])
        self.assertIn(Capability.PARSED, device.capabilities)

    async def test_command_without_a_template_is_non_fatal(self) -> None:
        run_commands = AsyncMock(
            return_value=(
                _result("a", "show clock", "show clock\n15:22:13\nsw1#"),
                _result("a", "show ip interface brief", IP_BRIEF),
            )
        )
        with _Harness(run_commands):
            outcomes = await _run(
                {"commands": ["show clock", "show ip interface brief"], "parser": "textfsm"},
                _context(_driver_device("a")),
            )
        self.assertEqual([o.name for o in outcomes], ["success"])
        parsed = outcomes[0].context.devices["a"].parsed["parsed"]
        self.assertIsNone(parsed["show clock"]["parsed"])
        self.assertIn("no template", parsed["show clock"]["error"])
        self.assertIsNotNone(parsed["show ip interface brief"]["parsed"])

    async def test_missing_driver_is_an_error_entry_unless_overridden(self) -> None:
        command = "show ip interface brief"
        run_commands = AsyncMock(return_value=(_result("a", command, IP_BRIEF),))
        with _Harness(run_commands):
            outcomes = await _run(
                {"commands": [command], "parser": "textfsm"}, _context(_driver_device("a", None))
            )
        self.assertIn(
            "network driver", outcomes[0].context.devices["a"].parsed["parsed"][command]["error"]
        )

        with _Harness(run_commands):
            outcomes = await _run(
                {
                    "commands": [command],
                    "parser": "textfsm",
                    "network_driver_override": "cisco_ios",
                },
                _context(_driver_device("a", None)),
            )
        self.assertIsNotNone(outcomes[0].context.devices["a"].parsed["parsed"][command]["parsed"])

    async def test_bad_parser_or_key_raises_before_any_io(self) -> None:
        for extra in ({"parser": "genie"}, {"parser": "textfsm", "parsed_output_key": "1 bad"}):
            with self.subTest(extra=extra), _Harness() as h:
                with self.assertRaises(ValueError):
                    await _run({"commands": ["show x"], **extra}, _context(_driver_device("a")))
                h.source_config.resolve_credentials.assert_not_called()

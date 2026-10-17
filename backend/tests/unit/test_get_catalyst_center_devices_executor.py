"""Tests for the get-catalyst-center-devices executor (mocked service layer, no network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.catalyst_center import CatalystCenterDevice
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterAuthError,
    CatalystCenterTooManyDevicesError,
    CatalystCenterValidationError,
)
from services.catalyst_center.source_config_service import CatalystCenterSourceNotFoundError
from workflow_steps.get_catalyst_center_devices.config import get_config
from workflow_steps.get_catalyst_center_devices.executor import execute

MODULE = "workflow_steps.get_catalyst_center_devices.executor"


def _device(i: int, **overrides) -> CatalystCenterDevice:
    data = {
        "id": f"uuid-{i}",
        "hostname": f"sw{i}",
        "management_ip": f"10.10.20.{170 + i}",
        "software_type": "IOS-XE",
        "raw": {"id": f"uuid-{i}", "hostname": f"sw{i}"},
    }
    data.update(overrides)
    return CatalystCenterDevice(**data)


def _context(**devices: DeviceContext) -> WorkflowContext:
    return WorkflowContext(run_id="run-1", workflow_id="wf-1", devices=devices)


def _config(**overrides) -> dict:
    base = {
        "catalyst_center_source_id": "lab-cc",
        "filters": {"hostnames": ["sw.*"]},
    }
    base.update(overrides)
    return base


class _Harness:
    """Patches the DB session + service_factory builders around one execute() call."""

    def __init__(self, devices=None, search_side_effect=None, resolve_side_effect=None):
        self.device_service = MagicMock()
        self.device_service.search_devices = AsyncMock(
            return_value=tuple(devices if devices is not None else (_device(1), _device(2))),
            side_effect=search_side_effect,
        )
        self.source_config = MagicMock()
        self.source_config.resolve_credentials.return_value = MagicMock(name="credentials")
        if resolve_side_effect is not None:
            self.source_config.resolve_credentials.side_effect = resolve_side_effect
        self.build_source_config = MagicMock(return_value=self.source_config)
        self.build_device_service = MagicMock(return_value=self.device_service)

    def __enter__(self):
        self._patches = [
            patch(f"{MODULE}.object_session", return_value=MagicMock()),
            patch(
                "service_factory.build_catalyst_center_source_config_service",
                self.build_source_config,
            ),
            patch(
                "service_factory.build_catalyst_center_device_service", self.build_device_service
            ),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


async def _run(config: dict, context: WorkflowContext | None = None):
    run = MagicMock()
    run.id = 1
    return await execute(
        config=config,
        context=context or _context(),
        run=run,
        artifact_service=InMemoryArtifactService(),
        node_id="node-1",
        device_sessions=MagicMock(),
    )


class SuccessPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_one_success_outcome_with_devices(self) -> None:
        with _Harness() as h:
            outcomes = await _run(_config())

        self.assertEqual([o.name for o in outcomes], ["success"])
        outcome = outcomes[0]
        self.assertEqual(set(outcome.context.devices), {"uuid-1", "uuid-2"})
        self.assertEqual(outcome.summary, "found 2 device(s)")
        self.assertEqual(outcome.context.metadata["node-1.source_id"], "lab-cc")
        self.assertEqual(outcome.context.metadata["node-1.total"], 2)
        h.source_config.resolve_credentials.assert_called_once_with("lab-cc")

    async def test_devices_carry_catalyst_center_identity(self) -> None:
        with _Harness():
            outcomes = await _run(_config())

        device = outcomes[0].context.devices["uuid-1"]
        self.assertEqual(device.source, "catalyst_center")
        self.assertEqual(device.source_id, "lab-cc")
        self.assertEqual(device.network_driver, "cisco_xe")
        self.assertEqual(device.capabilities, {Capability.IDENTITY})
        self.assertEqual(device.status, DeviceStatus.OK)
        self.assertIn("catalyst_center", device.attribute_bags)

    async def test_filters_and_cap_reach_the_device_service(self) -> None:
        with _Harness() as h:
            await _run(
                _config(filters={"roles": ["ACCESS"], "cidr": "10.10.20.0/24"}, max_devices="25")
            )

        filters = h.device_service.search_devices.await_args.args[0]
        self.assertEqual(filters.roles, ("ACCESS",))
        self.assertEqual(filters.cidr, "10.10.20.0/24")
        self.assertEqual(h.device_service.search_devices.await_args.kwargs["max_devices"], 25)

    async def test_existing_devices_are_preserved(self) -> None:
        upstream = DeviceContext(id="old", name="old", hostname="old", source="nautobot")
        with _Harness(devices=[_device(1)]):
            outcomes = await _run(_config(), _context(old=upstream))
        self.assertEqual(set(outcomes[0].context.devices), {"old", "uuid-1"})

    async def test_zero_matches_is_a_normal_success(self) -> None:
        with _Harness(devices=[]):
            outcomes = await _run(_config())
        self.assertEqual(outcomes[0].name, "success")
        self.assertEqual(outcomes[0].summary, "found 0 device(s)")
        self.assertEqual(outcomes[0].context.metadata["node-1.total"], 0)

    async def test_does_not_mutate_the_input_context(self) -> None:
        context = _context()
        with _Harness():
            await _run(_config(), context)
        self.assertEqual(context.devices, {})
        self.assertEqual(context.metadata, {})


class FanOutTests(unittest.IsolatedAsyncioTestCase):
    async def test_fan_out_metadata_added_when_enabled(self) -> None:
        fan_out = {"enabled": True, "mode": "per_device", "chunk_size": 1, "max_concurrency": 2}
        with _Harness():
            outcomes = await _run(_config(fan_out=fan_out))
        self.assertIn("_fan_out", outcomes[0].context.metadata)

    async def test_no_fan_out_metadata_by_default(self) -> None:
        with _Harness():
            outcomes = await _run(_config())
        self.assertNotIn("_fan_out", outcomes[0].context.metadata)


class ConfigGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_source_id(self) -> None:
        with _Harness() as h, self.assertRaisesRegex(ValueError, "catalyst_center_source_id"):
            await _run(_config(catalyst_center_source_id="  "))
        h.build_source_config.assert_not_called()

    async def test_no_filters_without_allow_all_is_rejected_before_any_io(self) -> None:
        for filters in ({}, None, {"hostnames": [], "roles": ["  "]}):
            with _Harness() as h, self.assertRaisesRegex(ValueError, "allow_all"):
                await _run(_config(filters=filters))
            h.build_source_config.assert_not_called()
            h.device_service.search_devices.assert_not_awaited()

    async def test_allow_all_permits_empty_filters(self) -> None:
        with _Harness() as h:
            outcomes = await _run(_config(filters={}, allow_all=True))
        self.assertEqual(outcomes[0].name, "success")
        self.assertTrue(h.device_service.search_devices.await_args.args[0].is_empty)

    async def test_invalid_filters_are_a_config_error(self) -> None:
        with _Harness(), self.assertRaisesRegex(ValueError, "get-catalyst-center-devices"):
            await _run(_config(filters={"hostname": ["sw1"]}))

    async def test_invalid_cidr_is_a_config_error(self) -> None:
        with _Harness(), self.assertRaisesRegex(ValueError, "CIDR"):
            await _run(_config(filters={"cidr": "10.0.0.0/99"}))

    async def test_max_devices_parsing(self) -> None:
        for raw, expected in ((None, None), ("", None), (5, 5), ("7", 7), (" 9 ", 9)):
            with _Harness() as h:
                await _run(_config(max_devices=raw))
            self.assertEqual(
                h.device_service.search_devices.await_args.kwargs["max_devices"], expected, raw
            )

    async def test_bad_max_devices_is_rejected(self) -> None:
        for raw in (0, -1, True, "abc", "1.5", 10**9, [3]):
            with _Harness() as h, self.assertRaisesRegex(ValueError, "max_devices"):
                await _run(_config(max_devices=raw))
            h.build_source_config.assert_not_called()


class SourceResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_source_is_a_config_error(self) -> None:
        with (
            _Harness(resolve_side_effect=CatalystCenterSourceNotFoundError("lab-cc")),
            self.assertRaisesRegex(ValueError, "not found"),
        ):
            await _run(_config())

    async def test_credential_problem_is_a_config_error(self) -> None:
        with (
            _Harness(resolve_side_effect=CatalystCenterValidationError("no username")),
            self.assertRaisesRegex(ValueError, "no username"),
        ):
            await _run(_config())

    async def test_missing_db_session_is_a_runtime_error(self) -> None:
        with _Harness(), patch(f"{MODULE}.object_session", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "no active DB session"):
                await _run(_config())


class FetchErrorMappingTests(unittest.IsolatedAsyncioTestCase):
    async def test_too_many_devices_is_a_config_error_naming_the_cap(self) -> None:
        with (
            _Harness(search_side_effect=CatalystCenterTooManyDevicesError(5)),
            self.assertRaisesRegex(ValueError, "more than 5"),
        ):
            await _run(_config(max_devices=5))

    async def test_validation_error_from_controller_is_a_config_error(self) -> None:
        with (
            _Harness(search_side_effect=CatalystCenterValidationError("bad filter")),
            self.assertRaisesRegex(ValueError, "bad filter"),
        ):
            await _run(_config())

    async def test_api_and_auth_errors_are_runtime_errors(self) -> None:
        for exc in (CatalystCenterAPIError("down"), CatalystCenterAuthError("denied")):
            with (
                _Harness(search_side_effect=exc),
                self.assertRaisesRegex(RuntimeError, "Catalyst Center request failed"),
            ):
                await _run(_config())


class LoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_logs_start_and_finish_with_step_id_prefix(self) -> None:
        with _Harness(), self.assertLogs(MODULE, level="INFO") as logs:
            await _run(_config())
        messages = [r.getMessage() for r in logs.records]
        self.assertTrue(messages[0].startswith("get-catalyst-center-devices started"))
        self.assertTrue(messages[-1].startswith("get-catalyst-center-devices finished"))
        self.assertIn("count=2", messages[-1])

    async def test_logs_do_not_include_filter_values_or_secrets(self) -> None:
        with _Harness(), self.assertLogs(MODULE, level="INFO") as logs:
            await _run(_config(filters={"hostnames": ["very-specific-host"]}))
        self.assertNotIn("very-specific-host", " ".join(r.getMessage() for r in logs.records))


class DefaultConfigTests(unittest.TestCase):
    def test_defaults_are_safe_and_complete(self) -> None:
        config = get_config()
        self.assertEqual(config["catalyst_center_source_id"], "")
        self.assertIs(config["allow_all"], False)
        self.assertIsNone(config["max_devices"])
        self.assertFalse(config["fan_out"]["enabled"])
        self.assertEqual(config["filters"], {})

    def test_get_config_returns_a_fresh_object_each_call(self) -> None:
        first = get_config()
        first["filters"]["roles"] = ["x"]
        self.assertEqual(get_config()["filters"], {})

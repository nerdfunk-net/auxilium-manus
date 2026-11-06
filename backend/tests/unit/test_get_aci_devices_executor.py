"""Tests for the get-aci-devices executor and the DeviceContext builder (no network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.aci import AciDevice
from models.failure import failure_from_exception
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.aci.common.exceptions import (
    AciAPIError,
    AciAuthError,
    AciTooManyDevicesError,
    AciValidationError,
)
from services.aci.source_config_service import AciSourceNotFoundError
from services.artifacts import InMemoryArtifactService
from workflow_steps.common.device_builders import device_context_from_aci
from workflow_steps.get_aci_devices.config import get_config
from workflow_steps.get_aci_devices.executor import execute

MODULE = "workflow_steps.get_aci_devices.executor"


def _device(node_id: int, **overrides) -> AciDevice:
    data = {
        "node_id": node_id,
        "name": f"leaf-{node_id}",
        "role": "leaf",
        "pod_id": 1,
        "model": "N9K-C9396PX",
        "serial_number": f"TEP-1-{node_id}",
        "software_version": "simsw-6.1(4h)",
        "fabric_state": "active",
        "system_state": "in-service",
        "tep_address": f"10.0.64.{node_id}",
        "dn": f"topology/pod-1/node-{node_id}",
        "raw": {"fabric_node": {"id": str(node_id)}, "top_system": {}},
    }
    data.update(overrides)
    return AciDevice(**data)


def _context(**devices: DeviceContext) -> WorkflowContext:
    return WorkflowContext(run_id="run-1", workflow_id="wf-1", devices=devices)


def _config(**overrides) -> dict:
    base = {"aci_source_id": "lab-aci", "filters": {"roles": ["leaf"]}}
    base.update(overrides)
    return base


class _Harness:
    """Patches the DB session + service_factory builders around one execute() call."""

    def __init__(self, devices=None, search_side_effect=None, resolve_side_effect=None):
        self.device_service = MagicMock()
        self.device_service.search = AsyncMock(
            return_value=list(devices if devices is not None else (_device(101), _device(102))),
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
            patch("service_factory.build_aci_source_config_service", self.build_source_config),
            patch("service_factory.build_aci_device_service", self.build_device_service),
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


class DeviceContextBuilderTests(unittest.TestCase):
    def test_identity_fields(self) -> None:
        ctx = device_context_from_aci(_device(101, management_ip="10.1.1.101"), source_id="lab-aci")
        self.assertEqual(ctx.id, "aci-lab-aci-101")
        self.assertEqual(ctx.name, "leaf-101")
        self.assertEqual(ctx.hostname, "10.1.1.101")
        self.assertEqual(ctx.primary_ip4, "10.1.1.101")
        self.assertEqual(ctx.source, "aci")
        self.assertEqual(ctx.source_id, "lab-aci")
        self.assertEqual(ctx.platform, "Cisco ACI")
        self.assertEqual(ctx.capabilities, {Capability.IDENTITY})
        self.assertEqual(ctx.status, DeviceStatus.OK)

    def test_no_management_ip_falls_back_to_the_name_and_never_uses_the_tep(self) -> None:
        ctx = device_context_from_aci(_device(101), source_id="lab-aci")
        self.assertIsNone(ctx.primary_ip4)
        self.assertEqual(ctx.hostname, "leaf-101")
        self.assertNotIn("10.0.64", ctx.hostname)

    def test_driver_is_left_unset(self) -> None:
        # ACI is a data source only for now; SSH steps must not be told a driver we did not verify.
        self.assertIsNone(device_context_from_aci(_device(101), source_id="x").network_driver)

    def test_ids_do_not_collide_across_sources(self) -> None:
        a = device_context_from_aci(_device(101), source_id="fab-a")
        b = device_context_from_aci(_device(101), source_id="fab-b")
        self.assertNotEqual(a.id, b.id)

    def test_attribute_bag_holds_normalized_fields_and_a_copy_of_the_raw_record(self) -> None:
        device = _device(101)
        ctx = device_context_from_aci(device, source_id="lab-aci")
        bag = ctx.attribute_bags["aci"]
        self.assertEqual(bag["node_id"], 101)
        self.assertEqual(bag["model"], "N9K-C9396PX")
        self.assertEqual(bag["fabric_state"], "active")
        self.assertEqual(bag["raw"]["fabric_node"]["id"], "101")
        bag["raw"]["fabric_node"]["id"] = "changed"
        self.assertEqual(device.raw["fabric_node"]["id"], "101")


class SuccessPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_one_success_outcome_with_devices(self) -> None:
        with _Harness() as h:
            outcomes = await _run(_config())

        self.assertEqual([o.name for o in outcomes], ["success"])
        outcome = outcomes[0]
        self.assertEqual(set(outcome.context.devices), {"aci-lab-aci-101", "aci-lab-aci-102"})
        self.assertEqual(outcome.summary, "found 2 device(s)")
        self.assertEqual(outcome.context.metadata["node-1.source_id"], "lab-aci")
        self.assertEqual(outcome.context.metadata["node-1.total"], 2)
        h.source_config.resolve_credentials.assert_called_once_with("lab-aci")

    async def test_filters_and_cap_reach_the_device_service(self) -> None:
        with _Harness() as h:
            await _run(
                _config(filters={"roles": ["spine"], "cidr": "10.1.1.0/24"}, max_devices="25")
            )
        filters = h.device_service.search.await_args.args[0]
        self.assertEqual(filters.roles, ("spine",))
        self.assertEqual(filters.cidr, "10.1.1.0/24")
        self.assertEqual(h.device_service.search.await_args.kwargs["max_devices"], 25)

    async def test_existing_devices_are_preserved_and_the_input_is_not_mutated(self) -> None:
        upstream = DeviceContext(id="old", name="old", hostname="old", source="nautobot")
        context = _context(old=upstream)
        with _Harness(devices=[_device(101)]):
            outcomes = await _run(_config(), context)
        self.assertEqual(set(outcomes[0].context.devices), {"old", "aci-lab-aci-101"})
        self.assertEqual(set(context.devices), {"old"})
        self.assertNotIn("node-1.total", context.metadata)

    async def test_zero_matches_is_a_normal_success(self) -> None:
        with _Harness(devices=[]):
            outcomes = await _run(_config())
        self.assertEqual(outcomes[0].summary, "found 0 device(s)")
        self.assertEqual(outcomes[0].context.metadata["node-1.total"], 0)

    async def test_allow_all_selects_everything_without_filters(self) -> None:
        for flag in (True, "true"):
            with self.subTest(flag=flag), _Harness() as h:
                await _run(_config(filters={}, allow_all=flag))
            self.assertTrue(h.device_service.search.await_args.args[0].is_empty)

    async def test_fan_out_metadata_is_set_when_enabled(self) -> None:
        fan_out = {"enabled": True, "mode": "per_device", "chunk_size": 1, "max_concurrency": 0}
        with _Harness():
            outcomes = await _run(_config(fan_out=fan_out))
        self.assertIn("_fan_out", outcomes[0].context.metadata)

    async def test_fan_out_metadata_is_absent_when_disabled(self) -> None:
        with _Harness():
            outcomes = await _run(_config(fan_out=get_config()["fan_out"]))
        self.assertNotIn("_fan_out", outcomes[0].context.metadata)


class ConfigErrorTests(unittest.IsolatedAsyncioTestCase):
    async def _expect_value_error(self, config: dict, **harness) -> str:
        with _Harness(**harness):
            with self.assertRaises(ValueError) as ctx:
                await _run(config)
        return str(ctx.exception)

    async def test_missing_source_id(self) -> None:
        for value in ("", "  ", None):
            message = await self._expect_value_error(_config(aci_source_id=value))
            self.assertIn("aci_source_id is not configured", message)

    async def test_no_filters_without_allow_all(self) -> None:
        message = await self._expect_value_error(_config(filters={}))
        self.assertIn("allow_all", message)

    async def test_allow_all_false_string_still_requires_a_filter(self) -> None:
        await self._expect_value_error(_config(filters={}, allow_all="false"))

    async def test_invalid_filter_is_a_config_error_naming_the_step(self) -> None:
        message = await self._expect_value_error(_config(filters={"hostnames": ["x"]}))
        self.assertIn("get-aci-devices", message)
        self.assertIn("Unknown filter", message)

    async def test_controller_role_is_refused(self) -> None:
        message = await self._expect_value_error(_config(filters={"roles": ["controller"]}))
        self.assertIn("leaf or spine", message)

    async def test_invalid_max_devices(self) -> None:
        for bad in (0, -3, True, 1.5, "abc", 2_000_000):
            with self.subTest(max_devices=bad):
                message = await self._expect_value_error(_config(max_devices=bad))
                self.assertIn("max_devices", message)

    async def test_blank_max_devices_means_no_cap(self) -> None:
        for blank in (None, "", "  "):
            with self.subTest(blank=blank), _Harness() as h:
                await _run(_config(max_devices=blank))
            self.assertIsNone(h.device_service.search.await_args.kwargs["max_devices"])

    async def test_unknown_source(self) -> None:
        message = await self._expect_value_error(
            _config(), resolve_side_effect=AciSourceNotFoundError("lab-aci")
        )
        self.assertIn("'lab-aci' not found", message)

    async def test_source_without_a_usable_credential(self) -> None:
        message = await self._expect_value_error(
            _config(), resolve_side_effect=AciValidationError("no linked credential")
        )
        self.assertIn("no linked credential", message)

    async def test_too_many_devices_is_a_config_error_not_an_outage(self) -> None:
        message = await self._expect_value_error(
            _config(max_devices=2), search_side_effect=AciTooManyDevicesError(2)
        )
        self.assertIn("more than 2 devices", message)

    async def test_missing_db_session(self) -> None:
        with patch(f"{MODULE}.object_session", return_value=None):
            with self.assertRaises(RuntimeError):
                await _run(_config())


class ApicFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_apic_errors_become_runtime_errors_that_keep_the_classification(self) -> None:
        cases = [
            (AciAuthError("denied", http_status=403, code="request_denied"), "permission_denied"),
            (AciAPIError("down", http_status=503), "server_error"),
            (AciAPIError("slow", code="timeout"), "timeout"),
        ]
        for error, kind in cases:
            with self.subTest(kind=kind), _Harness(search_side_effect=error):
                with self.assertRaises(RuntimeError) as ctx:
                    await _run(_config())
                self.assertIn("get-aci-devices", str(ctx.exception))
                self.assertIs(ctx.exception.__cause__, error)
                failure = failure_from_exception(ctx.exception)
                assert failure is not None
                self.assertEqual(failure.kind, kind)


if __name__ == "__main__":
    unittest.main()

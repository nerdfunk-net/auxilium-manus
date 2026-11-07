"""Tests for the get-aci-details executor (mocked service layer, no network)."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.aci import AciDevice
from models.aci_facts import (
    AciDeviceDetails,
    AciFaults,
    AciHealth,
    AciInterface,
    AciSoftware,
)
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.aci.common.exceptions import AciAPIError, AciValidationError
from services.aci.source_config_service import AciSourceNotFoundError
from services.artifacts import InMemoryArtifactService
from workflow_steps.common.device_builders import device_context_from_aci
from workflow_steps.get_aci_details.config import get_config
from workflow_steps.get_aci_details.executor import (
    DEFAULT_FACTS,
    FACTS,
    execute,
)

FACTS_MODULE = "workflow_steps.common.aci_facts"
BUILD = "build_aci_details_service"


def _aci_device(node_id: int, *, source_id: str = "lab", pod_id: int = 1) -> DeviceContext:
    return device_context_from_aci(
        AciDevice(node_id=node_id, name=f"leaf-{node_id}", role="leaf", pod_id=pod_id),
        source_id=source_id,
    )


def _context(*devices: DeviceContext) -> WorkflowContext:
    return WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={d.id: d for d in devices})


def _service(**overrides) -> MagicMock:
    service = MagicMock()
    service.get_device_and_software = AsyncMock(
        return_value=(
            AciDeviceDetails(node_id=101, name="leaf-1"),
            AciSoftware(software_version="6.1(4h)"),
        )
    )
    service.get_hardware = AsyncMock(return_value=())
    service.get_interfaces = AsyncMock(return_value=(AciInterface(name="eth1/1", kind="physical"),))
    service.get_neighbors = AsyncMock(return_value=())
    service.get_vlans = AsyncMock(return_value=())
    service.get_health = AsyncMock(return_value=AciHealth(score=90))
    service.get_faults = AsyncMock(return_value=AciFaults())
    service.get_routes = AsyncMock(return_value=())
    service.get_protocols = AsyncMock(return_value=MagicMock(model_dump=lambda mode: {}))
    service.get_endpoints = AsyncMock(return_value=())
    service.get_vpc = AsyncMock(return_value=MagicMock(model_dump=lambda mode: {}))
    service.get_epgs = AsyncMock(return_value=())
    service.get_contracts = AsyncMock(return_value=MagicMock(model_dump=lambda mode: {}))
    for name, mock in overrides.items():
        setattr(service, name, mock)
    return service


class _Patched:
    """Patches the DB session, credential resolution and the details-service builder."""

    def __init__(self, service: MagicMock, resolve_side_effect=None, db=MagicMock()):
        self.service = service
        self.source_config = MagicMock()
        if resolve_side_effect is not None:
            self.source_config.resolve_credentials.side_effect = resolve_side_effect
        self.builder = MagicMock(return_value=service)
        self._db = db

    def __enter__(self):
        self._patches = [
            patch(f"{FACTS_MODULE}.object_session", return_value=self._db),
            patch(
                "service_factory.build_aci_source_config_service", return_value=self.source_config
            ),
            patch(f"service_factory.{BUILD}", self.builder),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


async def _run(config: dict, context: WorkflowContext):
    run = MagicMock()
    run.id = 1
    return await execute(
        config=config,
        context=context,
        run=run,
        artifact_service=InMemoryArtifactService(),
        node_id="node-1",
        device_sessions=MagicMock(),
    )


class ConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_config_raises_before_any_io(self) -> None:
        bad = (
            {"facts": []},
            {"facts": ["bogus"]},
            {"facts": ["device", "bogus"]},
            {"facts": "device"},
            {"facts": [1]},
            {"facts": ["device"], "parsed_output_key": "1 bad"},
            {"facts": ["device"], "parsed_output_key": "has space"},
        )
        for config in bad:
            with self.subTest(config=config), _Patched(_service()) as p:
                with self.assertRaises(ValueError) as ctx:
                    await _run(config, _context(_aci_device(101)))
                self.assertIn("get-aci-details", str(ctx.exception))
                p.source_config.resolve_credentials.assert_not_called()

    async def test_unknown_facts_are_named_with_the_valid_choices(self) -> None:
        with _Patched(_service()), self.assertRaises(ValueError) as ctx:
            await _run({"facts": ["devices"]}, _context(_aci_device(101)))
        self.assertIn("devices", str(ctx.exception))
        self.assertIn("interfaces", str(ctx.exception))

    async def test_the_default_config_selects_the_documented_facts(self) -> None:
        config = get_config()
        self.assertEqual(tuple(config["facts"]), DEFAULT_FACTS)
        self.assertEqual(DEFAULT_FACTS, ("device", "software", "interfaces"))
        self.assertEqual(config["parsed_output_key"], "aci_details")

    async def test_the_fact_names_are_the_twelve_documented_ones(self) -> None:
        self.assertEqual(
            FACTS,
            (
                "device",
                "software",
                "hardware",
                "interfaces",
                "neighbors",
                "vlans",
                "health",
                "faults",
                "routes",
                "protocols",
                "endpoints",
                "vpc",
                "epgs",
                "contracts",
            ),
        )

    async def test_missing_facts_use_the_default(self) -> None:
        with _Patched(_service()) as p:
            outcomes = await _run({}, _context(_aci_device(101)))
        parsed = outcomes[0].context.devices["aci-lab-101"].parsed["aci_details"]
        self.assertEqual(list(parsed), ["device", "software", "interfaces"])
        p.service.get_hardware.assert_not_called()


class TargetTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_devices_is_a_noop_success(self) -> None:
        with _Patched(_service()) as p:
            outcomes = await _run({"facts": ["device"]}, _context())
        self.assertEqual([o.name for o in outcomes], ["success"])
        p.source_config.resolve_credentials.assert_not_called()

    async def test_a_device_from_another_source_fails_without_calling_the_apic(self) -> None:
        nautobot = DeviceContext(
            id="nb", name="x", hostname="x", source="nautobot", source_id="nb1"
        )
        with _Patched(_service()) as p:
            outcomes = await _run({"facts": ["device"]}, _context(nautobot, _aci_device(101)))
        by_name = {o.name: o for o in outcomes}
        failed = by_name["failure"].context.devices["nb"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[0].code, "not_aci_device")
        self.assertIn("aci-lab-101", by_name["success"].context.devices)
        p.service.get_device_and_software.assert_awaited_once()

    async def test_an_aci_device_without_a_node_in_its_bag_fails(self) -> None:
        broken = _aci_device(101).model_copy(update={"attribute_bags": {}})
        with _Patched(_service()) as p:
            outcomes = await _run({"facts": ["device"]}, _context(broken))
        failed = {o.name: o for o in outcomes}["failure"].context.devices[broken.id]
        self.assertEqual(failed.errors[0].code, "aci_node_unknown")
        p.service.get_device_and_software.assert_not_called()

    async def test_a_node_or_pod_that_is_not_a_positive_number_fails(self) -> None:
        for bag in (
            {"node_id": 0, "pod_id": 1},
            {"node_id": 101, "pod_id": -1},
            {"node_id": "x"},
            {"node_id": True, "pod_id": 1},
        ):
            broken = _aci_device(101).model_copy(update={"attribute_bags": {"aci": bag}})
            with self.subTest(bag=bag), _Patched(_service()) as p:
                outcomes = await _run({"facts": ["device"]}, _context(broken))
                failed = {o.name: o for o in outcomes}["failure"].context.devices[broken.id]
                self.assertEqual(failed.errors[0].code, "aci_node_unknown")
                p.service.get_device_and_software.assert_not_called()

    async def test_credentials_resolve_once_per_source(self) -> None:
        devices = [
            _aci_device(101, source_id="a"),
            _aci_device(102, source_id="a"),
            _aci_device(1, source_id="b"),
        ]
        with _Patched(_service()) as p:
            await _run({"facts": ["device"]}, _context(*devices))
        resolved = sorted(c.args[0] for c in p.source_config.resolve_credentials.call_args_list)
        self.assertEqual(resolved, ["a", "b"])
        self.assertEqual(p.builder.call_count, 3)  # one details service per device

    async def test_an_unknown_source_is_a_config_error(self) -> None:
        with (
            _Patched(_service(), AciSourceNotFoundError("lab")),
            self.assertRaisesRegex(ValueError, "'lab' not found"),
        ):
            await _run({"facts": ["device"]}, _context(_aci_device(101)))

    async def test_a_source_without_a_usable_credential_is_a_config_error(self) -> None:
        with (
            _Patched(_service(), AciValidationError("no linked credential")),
            self.assertRaisesRegex(ValueError, "no linked credential"),
        ):
            await _run({"facts": ["device"]}, _context(_aci_device(101)))

    async def test_a_missing_db_session_is_a_runtime_error(self) -> None:
        with _Patched(_service(), db=None), self.assertRaises(RuntimeError):
            await _run({"facts": ["device"]}, _context(_aci_device(101)))


class CollectTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_fact_calls_its_service_method_with_pod_and_node(self) -> None:
        expected = {
            "hardware": "get_hardware",
            "interfaces": "get_interfaces",
            "neighbors": "get_neighbors",
            "vlans": "get_vlans",
            "health": "get_health",
            "faults": "get_faults",
            "routes": "get_routes",
            "protocols": "get_protocols",
            "endpoints": "get_endpoints",
            "vpc": "get_vpc",
            "epgs": "get_epgs",
            "contracts": "get_contracts",
        }
        for fact, method in expected.items():
            with self.subTest(fact=fact), _Patched(_service()) as p:
                await _run({"facts": [fact]}, _context(_aci_device(101, pod_id=2)))
                getattr(p.service, method).assert_awaited_once_with(2, 101)

    async def test_device_and_software_share_one_call(self) -> None:
        with _Patched(_service()) as p:
            outcomes = await _run({"facts": ["software", "device"]}, _context(_aci_device(101)))
        p.service.get_device_and_software.assert_awaited_once_with(1, 101)
        parsed = outcomes[0].context.devices["aci-lab-101"].parsed["aci_details"]
        self.assertEqual(list(parsed), ["device", "software"])
        self.assertEqual(parsed["device"]["parsed"]["name"], "leaf-1")
        self.assertEqual(parsed["software"]["parsed"]["software_version"], "6.1(4h)")

    async def test_facts_land_in_the_canonical_order_without_duplicates(self) -> None:
        with _Patched(_service()):
            outcomes = await _run(
                {"facts": ["interfaces", "device", "device", "health"]}, _context(_aci_device(101))
            )
        parsed = outcomes[0].context.devices["aci-lab-101"].parsed["aci_details"]
        self.assertEqual(list(parsed), ["device", "interfaces", "health"])

    async def test_entries_have_the_parsed_error_shape_and_the_device_gains_the_parsed_capability(
        self,
    ) -> None:
        with _Patched(_service()):
            outcomes = await _run({"facts": ["interfaces", "health"]}, _context(_aci_device(101)))
        device = outcomes[0].context.devices["aci-lab-101"]
        entry = device.parsed["aci_details"]["interfaces"]
        self.assertEqual(entry["error"], None)
        self.assertEqual(entry["parsed"][0]["name"], "eth1/1")
        self.assertEqual(
            device.parsed["aci_details"]["health"],
            {"parsed": AciHealth(score=90).model_dump(mode="json"), "error": None},
        )
        self.assertIn(Capability.PARSED, device.capabilities)
        self.assertEqual(device.status, DeviceStatus.OK)

    async def test_a_custom_output_key_keeps_the_other_parsed_data(self) -> None:
        device = _aci_device(101).model_copy(update={"parsed": {"other": {"x": 1}}})
        with _Patched(_service()):
            outcomes = await _run(
                {"facts": ["health"], "parsed_output_key": "fabric"}, _context(device)
            )
        parsed = outcomes[0].context.devices[device.id].parsed
        self.assertEqual(set(parsed), {"other", "fabric"})
        self.assertEqual(parsed["other"], {"x": 1})

    async def test_the_input_context_is_not_mutated(self) -> None:
        context = _context(_aci_device(101))
        before = context.model_dump()
        with _Patched(_service()):
            await _run({"facts": ["interfaces"]}, context)
        self.assertEqual(context.model_dump(), before)

    async def test_one_failing_fact_does_not_fail_the_device_or_the_other_facts(self) -> None:
        service = _service(
            get_interfaces=AsyncMock(side_effect=AciAPIError("APIC is down", http_status=503))
        )
        with _Patched(service):
            outcomes = await _run(
                {"facts": ["device", "interfaces", "health"]}, _context(_aci_device(101))
            )
        self.assertEqual([o.name for o in outcomes], ["success"])
        parsed = outcomes[0].context.devices["aci-lab-101"].parsed["aci_details"]
        self.assertEqual(parsed["interfaces"], {"parsed": None, "error": "APIC is down"})
        self.assertIsNotNone(parsed["device"]["parsed"])
        self.assertEqual(parsed["health"]["parsed"]["score"], 90)

    async def test_a_device_fails_only_when_every_fact_failed_and_keeps_the_structured_failure(
        self,
    ) -> None:
        err = AciAPIError("APIC is down", http_status=503)
        service = _service(
            get_interfaces=AsyncMock(side_effect=err), get_health=AsyncMock(side_effect=err)
        )
        with _Patched(service):
            outcomes = await _run({"facts": ["interfaces", "health"]}, _context(_aci_device(101)))
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        failed = outcomes[1].context.devices["aci-lab-101"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[0].code, "aci_error")
        self.assertEqual(failed.errors[0].step_id, "get-aci-details")
        self.assertEqual(failed.errors[0].failure.kind, "server_error")
        self.assertEqual(failed.parsed["aci_details"]["health"]["error"], "APIC is down")
        self.assertEqual(outcomes[0].context.devices, {})

    async def test_a_failed_device_and_software_call_fails_both_entries(self) -> None:
        service = _service(
            get_device_and_software=AsyncMock(side_effect=AciAPIError("nope", code="transport"))
        )
        with _Patched(service):
            outcomes = await _run({"facts": ["device", "software"]}, _context(_aci_device(101)))
        failed = {o.name: o for o in outcomes}["failure"].context.devices["aci-lab-101"]
        self.assertEqual(failed.parsed["aci_details"]["device"]["error"], "nope")
        self.assertEqual(failed.parsed["aci_details"]["software"]["error"], "nope")

    async def test_one_bad_device_does_not_stop_the_others(self) -> None:
        async def interfaces(pod_id: int, node_id: int):
            if node_id == 102:
                raise AciAPIError("gone", http_status=404)
            return (AciInterface(name="eth1/1", kind="physical"),)

        with _Patched(_service(get_interfaces=interfaces)):
            outcomes = await _run(
                {"facts": ["interfaces"]}, _context(_aci_device(101), _aci_device(102))
            )
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["success"].context.devices), ["aci-lab-101"])
        self.assertEqual(list(by_name["failure"].context.devices), ["aci-lab-102"])

    async def test_an_unexpected_error_is_not_swallowed(self) -> None:
        service = _service(get_interfaces=AsyncMock(side_effect=RuntimeError("bug")))
        with _Patched(service), self.assertRaises(RuntimeError):
            await _run({"facts": ["interfaces"]}, _context(_aci_device(101)))

    async def test_facts_of_one_device_run_concurrently_but_bounded(self) -> None:
        state = {"now": 0, "max": 0}

        async def slow(*_args):
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
            await asyncio.sleep(0.01)
            state["now"] -= 1
            return ()

        overrides = {
            f"get_{n}": slow
            for n in ("hardware", "interfaces", "neighbors", "vlans", "routes", "endpoints")
        }
        with _Patched(_service(**overrides)):
            await _run(
                {"facts": ["hardware", "interfaces", "neighbors", "vlans", "routes", "endpoints"]},
                _context(_aci_device(101)),
            )
        self.assertGreater(state["max"], 1)
        self.assertLessEqual(state["max"], 4)

    async def test_start_and_finish_are_logged(self) -> None:
        with (
            _Patched(_service()),
            self.assertLogs("workflow_steps.common.fact_entries", level="INFO") as logs,
        ):
            await _run({"facts": ["device"]}, _context(_aci_device(101)))
        text = "\n".join(logs.output)
        self.assertIn("get-aci-details started", text)
        self.assertIn("get-aci-details finished success=1 failure=0", text)


if __name__ == "__main__":
    unittest.main()

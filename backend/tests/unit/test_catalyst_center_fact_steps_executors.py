"""Executors of the details, topology and health steps (mocked services, no network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.catalyst_center_facts import (
    CatalystCenterDeviceDetails,
    CatalystCenterHealth,
    CatalystCenterInterface,
    CatalystCenterSoftware,
    CatalystCenterTopology,
    CatalystCenterTopologyLink,
    CatalystCenterTopologyNode,
)
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.catalyst_center.common.exceptions import CatalystCenterAPIError
from services.catalyst_center.source_config_service import CatalystCenterSourceNotFoundError
from workflow_steps.get_catalyst_center_details.executor import execute as details
from workflow_steps.get_catalyst_center_health.executor import execute as health
from workflow_steps.get_catalyst_center_topology.executor import execute as topology

FACTS = "workflow_steps.common.catalyst_center_facts"


def _device(
    device_id: str, *, source: str = "catalyst_center", source_id: str = "lab"
) -> DeviceContext:
    return DeviceContext(
        id=device_id, name=device_id, hostname=device_id, source=source, source_id=source_id
    )


def _context(*devices: DeviceContext) -> WorkflowContext:
    return WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={d.id: d for d in devices})


class _Patched:
    """Patches the DB session, credential resolution and one service builder."""

    def __init__(self, builder: str, service: MagicMock, resolve_side_effect=None):
        self.service = service
        self.source_config = MagicMock()
        if resolve_side_effect is not None:
            self.source_config.resolve_credentials.side_effect = resolve_side_effect
        self.builder = MagicMock(return_value=service)
        self._builder_name = builder

    def __enter__(self):
        self._patches = [
            patch(f"{FACTS}.object_session", return_value=MagicMock()),
            patch(
                "service_factory.build_catalyst_center_source_config_service",
                return_value=self.source_config,
            ),
            patch(f"service_factory.{self._builder_name}", self.builder),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


async def _run(execute, config: dict, context: WorkflowContext):
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


def _details_service(**overrides) -> MagicMock:
    service = MagicMock()
    service.get_device_and_software = AsyncMock(
        return_value=(
            CatalystCenterDeviceDetails(id="a", hostname="sw1", role="ACCESS"),
            CatalystCenterSoftware(software_type="IOS-XE", software_version="17.12"),
        )
    )
    service.get_interfaces = AsyncMock(return_value=(CatalystCenterInterface(name="Gi1/0/1"),))
    service.get_vlans = AsyncMock(return_value=())
    service.get_compliance = AsyncMock(side_effect=CatalystCenterAPIError("no compliance data"))
    for name, mock in overrides.items():
        setattr(service, name, mock)
    return service


BUILD_DETAILS = "build_catalyst_center_details_service"


class DetailsConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_config_raises_before_any_io(self) -> None:
        for config in (
            {"facts": []},
            {"facts": ["bogus"]},
            {"facts": "device"},
            {"facts": ["device"], "parsed_output_key": "1 bad"},
        ):
            with self.subTest(config=config), _Patched(BUILD_DETAILS, _details_service()) as p:
                with self.assertRaises(ValueError):
                    await _run(details, config, _context(_device("a")))
                p.source_config.resolve_credentials.assert_not_called()

    async def test_unknown_source_is_a_value_error(self) -> None:
        with _Patched(BUILD_DETAILS, _details_service(), CatalystCenterSourceNotFoundError("lab")):
            with self.assertRaisesRegex(ValueError, "'lab' not found"):
                await _run(details, {"facts": ["device"]}, _context(_device("a")))

    async def test_no_devices_is_a_noop_success(self) -> None:
        with _Patched(BUILD_DETAILS, _details_service()) as p:
            outcomes = await _run(details, {}, _context())
        self.assertEqual([o.name for o in outcomes], ["success"])
        p.builder.assert_not_called()


class DetailsFactTests(unittest.IsolatedAsyncioTestCase):
    async def test_defaults_read_device_and_interfaces_only(self) -> None:
        service = _details_service()
        with _Patched(BUILD_DETAILS, service):
            outcomes = await _run(details, {}, _context(_device("a")))
        device = outcomes[0].context.devices["a"]
        bag = device.parsed["catalyst_details"]
        self.assertEqual(list(bag), ["device", "interfaces"])
        self.assertEqual(bag["device"]["parsed"]["role"], "ACCESS")
        self.assertEqual(bag["interfaces"]["parsed"][0]["name"], "Gi1/0/1")
        self.assertIn(Capability.PARSED, device.capabilities)
        service.get_vlans.assert_not_awaited()
        service.get_compliance.assert_not_awaited()

    async def test_device_and_software_share_one_request(self) -> None:
        service = _details_service()
        with _Patched(BUILD_DETAILS, service):
            outcomes = await _run(
                details,
                {"facts": ["software", "device"], "parsed_output_key": "d"},
                _context(_device("a")),
            )
        service.get_device_and_software.assert_awaited_once_with("a")
        bag = outcomes[0].context.devices["a"].parsed["d"]
        self.assertEqual(list(bag), ["device", "software"])  # fixed order, not config order
        self.assertEqual(bag["software"]["parsed"]["software_version"], "17.12")

    async def test_a_failed_fact_is_recorded_without_failing_the_device(self) -> None:
        with _Patched(BUILD_DETAILS, _details_service()):
            outcomes = await _run(
                details, {"facts": ["device", "compliance"]}, _context(_device("a"))
            )
        self.assertEqual([o.name for o in outcomes], ["success"])
        bag = outcomes[0].context.devices["a"].parsed["catalyst_details"]
        self.assertIsNone(bag["compliance"]["parsed"])
        self.assertEqual(bag["compliance"]["error"], "no compliance data")
        self.assertIsNone(bag["device"]["error"])

    async def test_device_fails_only_when_every_fact_failed(self) -> None:
        boom = AsyncMock(side_effect=CatalystCenterAPIError("controller down"))
        service = _details_service(get_device_and_software=boom, get_interfaces=boom)
        with _Patched(BUILD_DETAILS, service):
            outcomes = await _run(
                details, {"facts": ["device", "interfaces"]}, _context(_device("a"))
            )
        failure = next(o for o in outcomes if o.name == "failure")
        failed = failure.context.devices["a"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[0].code, "catalyst_center_error")
        self.assertIn("controller down", failed.errors[0].message)

    async def test_non_catalyst_device_is_rejected_without_a_request(self) -> None:
        service = _details_service()
        with _Patched(BUILD_DETAILS, service):
            outcomes = await _run(details, {}, _context(_device("n", source="nautobot")))
        failure = next(o for o in outcomes if o.name == "failure")
        self.assertEqual(failure.context.devices["n"].errors[0].code, "not_catalyst_center_device")
        service.get_device_and_software.assert_not_awaited()

    async def test_each_source_resolves_its_own_credentials(self) -> None:
        with _Patched(BUILD_DETAILS, _details_service()) as p:
            await _run(
                details,
                {"facts": ["device"]},
                _context(_device("a", source_id="one"), _device("b", source_id="two")),
            )
        resolved = {c.args[0] for c in p.source_config.resolve_credentials.call_args_list}
        self.assertEqual(resolved, {"one", "two"})


def _graph() -> CatalystCenterTopology:
    return CatalystCenterTopology(
        nodes=(
            CatalystCenterTopologyNode(id="a", label="sw1", ip="10.0.0.1"),
            CatalystCenterTopologyNode(id="b", label="sw2", ip="10.0.0.2"),
        ),
        links=(
            CatalystCenterTopologyLink(
                source="a", target="b", start_port_name="Gi1", end_port_name="Gi2", status="up"
            ),
        ),
    )


BUILD_TOPOLOGY = "build_catalyst_center_topology_service"


class TopologyTests(unittest.IsolatedAsyncioTestCase):
    def _service(self, **overrides) -> MagicMock:
        service = MagicMock()
        service.get_physical_topology = AsyncMock(return_value=_graph())
        service.get_l3_topology = AsyncMock(return_value=_graph())
        for name, mock in overrides.items():
            setattr(service, name, mock)
        return service

    async def test_config_validation(self) -> None:
        for config in ({"topologies": []}, {"topologies": ["l3_bgp"]}, {"topologies": "physical"}):
            with self.subTest(config=config), _Patched(BUILD_TOPOLOGY, self._service()):
                with self.assertRaises(ValueError):
                    await _run(topology, config, _context(_device("a")))

    async def test_graph_is_fetched_once_per_source_and_sliced_per_device(self) -> None:
        service = self._service()
        with _Patched(BUILD_TOPOLOGY, service):
            outcomes = await _run(
                topology,
                {"topologies": ["physical", "l3_ospf"]},
                _context(_device("a"), _device("b")),
            )
        service.get_physical_topology.assert_awaited_once()
        service.get_l3_topology.assert_awaited_once_with("ospf")
        a = outcomes[0].context.devices["a"].parsed["catalyst_topology"]
        b = outcomes[0].context.devices["b"].parsed["catalyst_topology"]
        self.assertEqual(list(a), ["physical", "l3_ospf"])
        self.assertEqual(a["physical"]["parsed"]["links"][0]["remote_name"], "sw2")
        self.assertEqual(b["physical"]["parsed"]["links"][0]["remote_name"], "sw1")
        self.assertEqual(b["physical"]["parsed"]["links"][0]["local_port"], "Gi2")

    async def test_device_outside_the_graph_succeeds_with_no_links(self) -> None:
        with _Patched(BUILD_TOPOLOGY, self._service()):
            outcomes = await _run(topology, {}, _context(_device("zzz")))
        entry = outcomes[0].context.devices["zzz"].parsed["catalyst_topology"]["physical"]
        self.assertEqual(entry["parsed"], {"node": None, "links": []})

    async def test_one_failing_graph_is_a_per_topology_error(self) -> None:
        service = self._service(
            get_l3_topology=AsyncMock(side_effect=CatalystCenterAPIError("nope"))
        )
        with _Patched(BUILD_TOPOLOGY, service):
            outcomes = await _run(
                topology, {"topologies": ["physical", "l3_ospf"]}, _context(_device("a"))
            )
        bag = outcomes[0].context.devices["a"].parsed["catalyst_topology"]
        self.assertIsNone(bag["physical"]["error"])
        self.assertEqual(bag["l3_ospf"]["error"], "nope")

    async def test_all_graphs_failing_fails_the_device(self) -> None:
        service = self._service(
            get_physical_topology=AsyncMock(side_effect=CatalystCenterAPIError("down"))
        )
        with _Patched(BUILD_TOPOLOGY, service):
            outcomes = await _run(topology, {}, _context(_device("a")))
        self.assertIn("a", next(o for o in outcomes if o.name == "failure").context.devices)


BUILD_HEALTH = "build_catalyst_center_health_service"


class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_lands_under_the_output_key(self) -> None:
        service = MagicMock()
        service.get_device_health = AsyncMock(
            return_value=CatalystCenterHealth(
                overall_health=10.0, cpu=26.25, communication_state="REACHABLE"
            )
        )
        with _Patched(BUILD_HEALTH, service):
            outcomes = await _run(health, {"parsed_output_key": "h"}, _context(_device("a")))
        entry = outcomes[0].context.devices["a"].parsed["h"]["health"]
        self.assertEqual((entry["parsed"]["overall_health"], entry["error"]), (10.0, None))
        service.get_device_health.assert_awaited_once_with("a")

    async def test_controller_error_fails_the_device(self) -> None:
        service = MagicMock()
        service.get_device_health = AsyncMock(side_effect=CatalystCenterAPIError("no health data"))
        with _Patched(BUILD_HEALTH, service):
            outcomes = await _run(health, {}, _context(_device("a")))
        failed = next(o for o in outcomes if o.name == "failure").context.devices["a"]
        self.assertIn("no health data", failed.errors[0].message)

    async def test_bad_output_key_raises(self) -> None:
        with _Patched(BUILD_HEALTH, MagicMock()), self.assertRaises(ValueError):
            await _run(health, {"parsed_output_key": "no good"}, _context(_device("a")))

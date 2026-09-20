"""Tests for undefined-and-unused executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.batfish.credentials import BatfishConnection
from workflow_steps.common.batfish_context import store_batfish_snapshot
from workflow_steps.undefined_and_unused.executor import execute

_SERVICE_FACTORY_TARGET = "workflow_steps.undefined_and_unused.executor.service_factory"


def _device(device_id: str, name: str) -> DeviceContext:
    return DeviceContext(id=device_id, name=name, hostname=name, status=DeviceStatus.OK)


def _context_with_snapshot(devices: dict[str, DeviceContext]) -> WorkflowContext:
    context = WorkflowContext(run_id="run-uuid-1", workflow_id="7", devices=devices)
    return store_batfish_snapshot(
        context,
        connection=BatfishConnection(host="batfish", port=9996),
        network="manus-workflow-7",
        snapshot="run-42",
    )


_FILE_PARSE_STATUS_ROWS = [
    # partially_unrecognized is a real, common live-coordinator status (some
    # unrecognized lines, file still parsed) -- must still be treated as
    # analyzable, not a failure.
    {"File_Name": "configs/routera.cfg", "Status": "partially_unrecognized", "Nodes": ["routera"]},
    {"File_Name": "configs/routerb.cfg", "Status": "PASSED", "Nodes": ["routerb"]},
    {"File_Name": "configs/routerc.cfg", "Status": "PASSED", "Nodes": ["routerc"]},
    {"File_Name": "configs/routerd.cfg", "Status": "PASSED", "Nodes": ["routerd"]},
    {"File_Name": "configs/routere.cfg", "Status": "FAILED", "Nodes": ["routere"]},
    # routerf deliberately absent -- exercises the "no matching node" path.
]

_UNDEFINED_ROWS = [
    {
        "File_Name": "configs/routera.cfg",
        "Struct_Type": "route-map",
        "Ref_Name": "filter-bogons",
        "Context": "bgp inbound route-map",
        "Lines": {"filename": "configs/routera.cfg", "lines": [110]},
    },
    {
        "File_Name": "configs/routerc.cfg",
        "Struct_Type": "route-map",
        "Ref_Name": "filter-x",
        "Context": "bgp inbound route-map",
        "Lines": {"filename": "configs/routerc.cfg", "lines": [42]},
    },
]

_UNUSED_ROWS = [
    {
        "Structure_Type": "bgp peer-group",
        "Structure_Name": "as3",
        "Source_Lines": {"filename": "configs/routerb.cfg", "lines": [85]},
    },
    {
        "Structure_Type": "extended ipv4 access-list",
        "Structure_Name": "OLD-ACL",
        "Source_Lines": {"filename": "configs/routerc.cfg", "lines": [50]},
    },
]


class UndefinedAndUnusedExecutorTests(unittest.IsolatedAsyncioTestCase):
    def _make_batfish(self) -> MagicMock:
        batfish = MagicMock()
        batfish.file_parse_status = AsyncMock(return_value=_FILE_PARSE_STATUS_ROWS)
        batfish.undefined_references = AsyncMock(return_value=_UNDEFINED_ROWS)
        batfish.unused_structures = AsyncMock(return_value=_UNUSED_ROWS)
        return batfish

    async def test_devices_route_to_expected_buckets(self) -> None:
        devices = {
            "id-a": _device("id-a", "routerA"),
            "id-b": _device("id-b", "routerB"),
            "id-c": _device("id-c", "routerC"),
            "id-d": _device("id-d", "routerD"),
            "id-e": _device("id-e", "routerE"),
            "id-f": _device("id-f", "routerF"),
            "id-g": _device("id-g", ""),  # no name at all
        }
        run = MagicMock()
        run.id = 1

        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = self._make_batfish()
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={},
                context=_context_with_snapshot(devices),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(set(by_name), {"success", "undefined", "unused", "failure"})

        self.assertEqual(set(by_name["success"].context.devices), {"id-d"})
        self.assertEqual(set(by_name["undefined"].context.devices), {"id-a", "id-c"})
        self.assertEqual(set(by_name["unused"].context.devices), {"id-b", "id-c"})
        self.assertEqual(set(by_name["failure"].context.devices), {"id-e", "id-f", "id-g"})

        # routerE failed on parse status, routerF had no matching Batfish
        # node, routerG had no name at all -- distinct error codes.
        failure_devices = by_name["failure"].context.devices
        self.assertEqual(failure_devices["id-e"].errors[-1].code, "parse_status")
        self.assertEqual(failure_devices["id-f"].errors[-1].code, "node_not_found")
        self.assertEqual(failure_devices["id-g"].errors[-1].code, "missing_name")

        # routerC lands in both undefined and unused with identical,
        # merge-safe device copies (both parsed keys present in each).
        undefined_c = by_name["undefined"].context.devices["id-c"]
        unused_c = by_name["unused"].context.devices["id-c"]
        self.assertIn("node-1.undefined_and_unused.undefined", undefined_c.parsed)
        self.assertIn("node-1.undefined_and_unused.unused", undefined_c.parsed)
        self.assertEqual(undefined_c.parsed, unused_c.parsed)

        # A clean device on the "success" outcome still carries
        # Capability.PARSED (empty-list findings) -- required by
        # post_step_guard since this step's registry entry declares
        # produces: [parsed]; only devices literally on the "success"
        # outcome are checked.
        success_d = by_name["success"].context.devices["id-d"]
        self.assertIn(Capability.PARSED, success_d.capabilities)
        self.assertEqual(
            success_d.parsed["node-1.undefined_and_unused.undefined"], {"parsed": [], "error": None}
        )
        self.assertEqual(
            success_d.parsed["node-1.undefined_and_unused.unused"], {"parsed": [], "error": None}
        )

    async def test_nodes_filter_auto_derived_from_upstream_devices(self) -> None:
        devices = {
            "id-a": _device("id-a", "routerA"),
            "id-d": _device("id-d", "routerD"),
        }
        run = MagicMock()
        run.id = 1

        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = self._make_batfish()
            service_factory_mock.get_batfish_app_service.return_value = batfish

            await execute(
                config={},
                context=_context_with_snapshot(devices),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        # fileParseStatus itself takes no "nodes" parameter (see
        # query_file_parse_status's docstring) -- the auto-derived filter is
        # only observable on the two questions that do accept one.
        _, kwargs = batfish.file_parse_status.call_args
        self.assertNotIn("nodes", kwargs)
        _, kwargs = batfish.undefined_references.call_args
        self.assertEqual(kwargs["nodes"], "routera,routerd")
        _, kwargs = batfish.unused_structures.call_args
        self.assertEqual(kwargs["nodes"], "routera,routerd")

    async def test_explicit_nodes_config_overrides_auto_derivation(self) -> None:
        devices = {"id-a": _device("id-a", "routerA")}
        run = MagicMock()
        run.id = 1

        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = self._make_batfish()
            service_factory_mock.get_batfish_app_service.return_value = batfish

            await execute(
                config={"nodes": "/.*/"},
                context=_context_with_snapshot(devices),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        _, kwargs = batfish.undefined_references.call_args
        self.assertEqual(kwargs["nodes"], "/.*/")

    async def test_empty_devices_returns_empty_outcomes_without_querying_batfish(self) -> None:
        run = MagicMock()
        run.id = 1

        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            outcomes = await execute(
                config={},
                context=WorkflowContext(run_id="run-uuid-1", workflow_id="7"),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual({o.name for o in outcomes}, {"success", "undefined", "unused", "failure"})
        for outcome in outcomes:
            self.assertEqual(outcome.context.devices, {})
        service_factory_mock.get_batfish_app_service.assert_not_called()


if __name__ == "__main__":
    unittest.main()

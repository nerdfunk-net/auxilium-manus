"""Tests for workflow_steps/get_nautobot_attributes/executor.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from workflow_steps.get_nautobot_attributes import executor as mod
from workflow_steps.get_nautobot_attributes.executor import (
    _bind_nautobot,
    _fetch_device,
    _parse_config,
    execute,
)


def _device(did: str) -> DeviceContext:
    return DeviceContext(
        id=did, name=did, hostname=did, primary_ip4="10.0.0.1",
        capabilities={Capability.IDENTITY}, status=DeviceStatus.OK,
    )


class ParseConfigTests(unittest.TestCase):
    def test_missing_source_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config({})

    def test_parses_source_id_and_attributes(self) -> None:
        cfg = _parse_config({"nautobot_source_id": " src-1 ", "list_of_attributes": ["tags"]})
        self.assertEqual(cfg.source_id, "src-1")
        self.assertEqual(cfg.list_of_attributes, ["tags"])
        self.assertFalse(cfg.case_insensitive_lookup)
        self.assertTrue(cfg.normalize_cables)

    def test_parses_case_insensitive_lookup(self) -> None:
        cfg = _parse_config(
            {"nautobot_source_id": "src-1", "case_insensitive_lookup": True}
        )
        self.assertTrue(cfg.case_insensitive_lookup)


    def test_parses_normalize_cables(self) -> None:
        cfg = _parse_config({"nautobot_source_id": "s", "normalize_cables": False})
        self.assertFalse(cfg.normalize_cables)


class BindNautobotTests(unittest.TestCase):
    def test_no_db_session_raises(self) -> None:
        run = MagicMock()
        with patch.object(mod, "object_session", return_value=None):
            with self.assertRaises(RuntimeError):
                _bind_nautobot(run, "src-1")

    def test_resolver_error_propagates(self) -> None:
        run = MagicMock()
        with (
            patch.object(mod, "object_session", return_value=MagicMock()),
            patch.object(
                mod,
                "resolve_nautobot_credentials",
                side_effect=ValueError("get-nautobot-attributes: boom"),
            ),
        ):
            with self.assertRaises(ValueError):
                _bind_nautobot(run, "src-1")

    def test_valid_source_builds_credentials(self) -> None:
        run = MagicMock()
        creds = MagicMock(url="https://nb")
        with (
            patch.object(mod, "object_session", return_value=MagicMock()),
            patch.object(mod, "resolve_nautobot_credentials", return_value=creds),
            patch.object(mod.service_factory, "get_nautobot_app_service", return_value="svc"),
        ):
            resolved_creds, svc = _bind_nautobot(run, "src-1")
        self.assertIs(resolved_creds, creds)
        self.assertEqual(svc, "svc")


class FetchDeviceTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_device_dict(self) -> None:
        svc = MagicMock()
        svc.graphql_query = AsyncMock(return_value={"data": {"device": {"id": "x"}}})
        out = await _fetch_device(svc, MagicMock(), "x", {}, "query")
        self.assertEqual(out, {"id": "x"})

    async def test_returns_none_when_device_missing(self) -> None:
        svc = MagicMock()
        svc.graphql_query = AsyncMock(return_value={"data": {"device": None}, "errors": ["e"]})
        self.assertIsNone(await _fetch_device(svc, MagicMock(), "x", {}, "query"))


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    return run


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_devices_returns_success(self) -> None:
        outcomes = await execute(
            config={"nautobot_source_id": "s"},
            context=WorkflowContext(run_id="r", workflow_id="w", devices={}),
            run=_run(), artifact_service=MagicMock(), node_id="n", device_sessions=MagicMock(),
        )
        self.assertEqual([o.name for o in outcomes], ["success"])

    async def test_enriches_device_with_nautobot_bag(self) -> None:
        svc = MagicMock()
        svc.graphql_query = AsyncMock(
            return_value={"data": {"device": {
                "id": "nb-1", "name": "r1",
                "platform": {"name": "ios", "network_driver": "ios"},
                "_custom_field_data": {"site": "NYC"},
            }}}
        )
        ctx = WorkflowContext(run_id="r", workflow_id="w", devices={"d1": _device("d1")})
        resolver = AsyncMock(return_value="nb-1")
        with (
            patch.object(mod, "_bind_nautobot", return_value=(MagicMock(), svc)),
            patch.object(mod, "resolve_nautobot_device_id", resolver),
        ):
            outcomes = await execute(
                config={"nautobot_source_id": "s", "case_insensitive_lookup": True},
                context=ctx, run=_run(),
                artifact_service=MagicMock(), node_id="n", device_sessions=MagicMock(),
            )
        enriched = next(o for o in outcomes if o.name == "success").context.devices["d1"]
        self.assertEqual(enriched.attribute_bags["nautobot"]["custom_fields"], {"site": "NYC"})
        self.assertEqual(enriched.platform, "ios")
        self.assertIn(Capability.ATTRIBUTES, enriched.capabilities)
        self.assertTrue(resolver.call_args.kwargs["case_insensitive"])

    async def test_unresolved_device_routes_to_failure(self) -> None:
        ctx = WorkflowContext(run_id="r", workflow_id="w", devices={"d1": _device("d1")})
        with (
            patch.object(mod, "_bind_nautobot", return_value=(MagicMock(), MagicMock())),
            patch.object(mod, "resolve_nautobot_device_id", AsyncMock(return_value=None)),
        ):
            outcomes = await execute(
                config={"nautobot_source_id": "s"}, context=ctx, run=_run(),
                artifact_service=MagicMock(), node_id="n", device_sessions=MagicMock(),
            )
        by_name = {o.name: o for o in outcomes}
        failed = by_name["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[-1].code, "not_found")

    async def test_resolver_exception_routes_to_failure(self) -> None:
        ctx = WorkflowContext(run_id="r", workflow_id="w", devices={"d1": _device("d1")})
        with (
            patch.object(mod, "_bind_nautobot", return_value=(MagicMock(), MagicMock())),
            patch.object(
                mod, "resolve_nautobot_device_id", AsyncMock(side_effect=RuntimeError("boom"))
            ),
        ):
            outcomes = await execute(
                config={"nautobot_source_id": "s"}, context=ctx, run=_run(),
                artifact_service=MagicMock(), node_id="n", device_sessions=MagicMock(),
            )
        failed = {o.name: o for o in outcomes}["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[-1].code, "runtimeerror")


if __name__ == "__main__":
    unittest.main()


class InterfaceRedundancyGroupTests(unittest.TestCase):
    def test_query_selects_redundancy_groups_inside_interfaces(self) -> None:
        from services.nautobot.devices.attribute_bag import build_device_attributes_query

        query = build_device_attributes_query()
        start = query.index("interfaces @include(if: $get_interfaces)")
        end = query.index("console_ports @include")
        block = query[start:end]
        self.assertIn("interface_redundancy_groups {", block)
        for field in ("protocol_group_id", "virtual_ip {", "description"):
            self.assertIn(field, block)
        # The secrets group is never read by a write step: it must not land in the run data.
        self.assertNotIn("secrets_group", block)
        self.assertIn("interface_redundancy_group_associations", block)
        self.assertIn("namespace {", block)

    def test_association_priority_is_merged_into_the_groups(self) -> None:
        from services.nautobot.devices.attribute_bag import attributes_from_detail

        bag = attributes_from_detail(
            {
                "interfaces": [
                    {
                        "name": "Vlan200",
                        "interface_redundancy_groups": [{"id": "g1", "name": "hsrp-1"}],
                        "interface_redundancy_group_associations": [
                            {"priority": 110, "interface_redundancy_group": {"id": "g1"}}
                        ],
                    },
                    {"name": "Vlan100", "interface_redundancy_groups": []},
                ]
            }
        )
        vlan = bag["interfaces"][0]
        self.assertEqual(vlan["interface_redundancy_groups"][0]["priority"], 110)
        self.assertNotIn("interface_redundancy_group_associations", vlan)
        self.assertNotIn("priority", str(bag["interfaces"][1]))

    def test_redundancy_groups_pass_through_the_bag(self) -> None:
        from services.nautobot.devices.attribute_bag import attributes_from_detail

        groups = [{"id": "g1", "name": "HSRP-1", "virtual_ip": {"address": "10.0.0.30/27"}}]
        bag = attributes_from_detail(
            {"interfaces": [{"name": "Ethernet0/0", "interface_redundancy_groups": groups}]}
        )
        self.assertEqual(bag["interfaces"][0]["interface_redundancy_groups"], groups)

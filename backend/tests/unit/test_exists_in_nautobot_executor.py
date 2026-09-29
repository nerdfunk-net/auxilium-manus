"""Tests for workflow_steps/exists_in_nautobot/executor.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from workflow_steps.exists_in_nautobot import executor as mod
from workflow_steps.exists_in_nautobot.executor import _parse_config, execute

_UUID = "efce2684-f64d-4d27-9030-f0e71b1e45c0"


def _device(did: str = "d1", **overrides) -> DeviceContext:
    defaults = dict(
        id=did,
        name=did,
        hostname=did,
        primary_ip4="10.0.0.1/24",
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )
    defaults.update(overrides)
    return DeviceContext(**defaults)


def _context(*devices: DeviceContext) -> WorkflowContext:
    return WorkflowContext(run_id="r", workflow_id="w", devices={d.id: d for d in devices})


def _config(**overrides) -> dict:
    cfg = {"nautobot_source_id": "src-1", "strategy": "name"}
    cfg.update(overrides)
    return cfg


async def _run(config: dict, context: WorkflowContext, response=None, side_effect=None):
    service = MagicMock()
    service.graphql_query = AsyncMock(return_value=response, side_effect=side_effect)
    with patch.object(mod, "_bind_nautobot", return_value=(MagicMock(), service)):
        outcomes = await execute(
            config=config,
            context=context,
            run=MagicMock(id="r"),
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )
    return {o.name: o.context for o in outcomes}, service


class ParseConfigTests(unittest.TestCase):
    def test_missing_source_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config({"strategy": "name"})

    def test_invalid_strategy_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(strategy="nope"))

    def test_ip_strategy_without_expression_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(strategy="primary_ip", ip_address="  "))

    def test_defaults(self) -> None:
        parsed = _parse_config(_config())
        self.assertEqual(parsed.strategy, "name")
        self.assertFalse(parsed.case_insensitive)


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_name_found_routes_exists_and_sets_bag_id(self) -> None:
        dev = _device("R1")
        ctx = _context(dev)
        result, _ = await _run(_config(), ctx, {"data": {"devices": [{"id": _UUID, "name": "R1"}]}})
        self.assertEqual(list(result["exists"].devices), ["R1"])
        self.assertEqual(result["exists"].devices["R1"].attribute_bags["nautobot"]["id"], _UUID)
        self.assertEqual(result["non_existing"].devices, {})
        self.assertEqual(result["failure"].devices, {})

    async def test_name_not_found_routes_non_existing(self) -> None:
        result, _ = await _run(_config(), _context(_device("R1")), {"data": {"devices": []}})
        self.assertEqual(list(result["non_existing"].devices), ["R1"])
        self.assertNotIn("nautobot", result["non_existing"].devices["R1"].attribute_bags)

    async def test_primary_ip_strategy_uses_expression_and_strips_mask(self) -> None:
        result, service = await _run(
            _config(strategy="primary_ip", ip_address="{device.primary_ip4}"),
            _context(_device("R1")),
            {
                "data": {
                    "ip_addresses": [
                        {"address": "10.0.0.1/24", "primary_ip4_for": [{"id": _UUID, "name": "R1"}]}
                    ]
                }
            },
        )
        self.assertEqual(list(result["exists"].devices), ["R1"])
        self.assertEqual(service.graphql_query.call_args.args[1], {"address": ["10.0.0.1"]})

    async def test_interface_ip_strategy(self) -> None:
        response = {
            "data": {
                "ip_addresses": [
                    {"interface_assignments": [{"interface": {"device": {"id": _UUID}}}]}
                ]
            }
        }
        result, _ = await _run(
            _config(strategy="interface_ip", ip_address="192.168.178.120"),
            _context(_device("R1")),
            response,
        )
        self.assertEqual(result["exists"].devices["R1"].attribute_bags["nautobot"]["id"], _UUID)

    async def test_unresolved_ip_fails_device(self) -> None:
        dev = _device("R1", primary_ip4=None)
        result, service = await _run(
            _config(strategy="primary_ip", ip_address="{device.primary_ip4}"),
            _context(dev),
            {"data": {"devices": []}},
        )
        failed = result["failure"].devices["R1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[-1].code, "ip_unresolved")
        service.graphql_query.assert_not_called()

    async def test_query_exception_routes_failure(self) -> None:
        result, _ = await _run(_config(), _context(_device("R1")), side_effect=RuntimeError("down"))
        failed = result["failure"].devices["R1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[-1].step_id, "exists-in-nautobot")

    async def test_existing_nautobot_bag_keys_kept_and_input_not_mutated(self) -> None:
        dev = _device("R1", attribute_bags={"nautobot": {"role": {"name": "edge"}}})
        ctx = _context(dev)
        result, _ = await _run(_config(), ctx, {"data": {"devices": [{"id": _UUID, "name": "R1"}]}})
        bag = result["exists"].devices["R1"].attribute_bags["nautobot"]
        self.assertEqual(bag, {"role": {"name": "edge"}, "id": _UUID})
        self.assertEqual(dev.attribute_bags["nautobot"], {"role": {"name": "edge"}})

    async def test_devices_split_across_buckets_and_counts(self) -> None:
        service = MagicMock()

        async def query(_q, variables, _c):
            names = variables["names"]
            found = [{"id": _UUID, "name": names[0]}] if names[0] == "A" else []
            return {"data": {"devices": found}}

        service.graphql_query = AsyncMock(side_effect=query)
        with patch.object(mod, "_bind_nautobot", return_value=(MagicMock(), service)):
            outcomes = await execute(
                config=_config(),
                context=_context(_device("A"), _device("B")),
                run=MagicMock(id="r"),
                artifact_service=MagicMock(),
                node_id="n1",
                device_sessions=MagicMock(),
            )
        by_name = {o.name: o.context for o in outcomes}
        self.assertEqual(list(by_name["exists"].devices), ["A"])
        self.assertEqual(list(by_name["non_existing"].devices), ["B"])
        self.assertEqual(
            by_name["exists"].metadata["n1.exists_counts"],
            {"exists": 1, "non_existing": 1, "failure": 0},
        )

    async def test_no_devices_emits_all_outcomes(self) -> None:
        result, service = await _run(_config(), _context(), {"data": {}})
        self.assertEqual(set(result), {"exists", "non_existing", "failure"})
        service.graphql_query.assert_not_called()


if __name__ == "__main__":
    unittest.main()

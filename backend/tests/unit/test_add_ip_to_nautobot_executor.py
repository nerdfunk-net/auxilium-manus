"""Tests for workflow_steps/add_ip_to_nautobot/executor.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.nautobot.common.exceptions import NautobotAPIError
from workflow_steps.add_ip_to_nautobot import executor as mod
from workflow_steps.add_ip_to_nautobot.executor import _parse_config, execute

_NS_ID = "11111111-1111-1111-1111-111111111111"
_STATUS_ID = "44444444-4444-4444-4444-444444444444"
_PREFIX_ID = "22222222-2222-2222-2222-222222222222"
_IP_ID = "55555555-5555-5555-5555-555555555555"
_DEVICE_ID = "66666666-6666-6666-6666-666666666666"


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
    cfg = {
        "nautobot_source_id": "src-1",
        "ip_address": "192.168.178.10/24",
        "namespace": "Global",
        "status": "Active",
    }
    cfg.update(overrides)
    return cfg


def _containing(*prefixes: tuple[str, str]):
    async def rest_request(*, endpoint: str, method: str = "GET", data=None):
        assert "contains=" in endpoint, endpoint
        return {"results": [{"id": pid, "prefix": text} for pid, text in prefixes]}

    return rest_request


async def _run(
    config: dict, context: WorkflowContext, *, common=None, rest=None, device_id=_DEVICE_ID
):
    common = common or MagicMock()
    for name, value in (
        ("resolve_namespace_id", _NS_ID),
        ("resolve_status_id", _STATUS_ID),
        ("ensure_ip_address_exists", _IP_ID),
        ("resolve_interface_by_name", "77777777-7777-7777-7777-777777777777"),
        ("assign_ip_to_interface", {}),
        ("assign_primary_ip_to_device", True),
    ):
        if not isinstance(getattr(common, name, None), AsyncMock):
            setattr(common, name, AsyncMock(return_value=value))
    client = MagicMock()
    client.rest_request = AsyncMock(side_effect=rest or _containing())
    bound = mod._Bound(common=common, client=client, service=MagicMock(), credentials=MagicMock())
    with (
        patch.object(mod, "_bind_nautobot", return_value=bound),
        patch.object(mod, "resolve_nautobot_device_id", AsyncMock(return_value=device_id)),
    ):
        outcomes = await execute(
            config=config,
            context=context,
            run=MagicMock(id="r"),
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )
    return {o.name: o.context for o in outcomes}, common


class ParseConfigTests(unittest.TestCase):
    def test_missing_source(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(nautobot_source_id=""))

    def test_missing_ip(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(ip_address=" "))

    def test_reserved_result_attribute(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(result_attribute="parsed.ip"))

    def test_set_primary_needs_interface(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(set_primary=True))

    def test_bad_mask_length(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(default_mask_length=200))

    def test_defaults(self) -> None:
        parsed = _parse_config(_config(namespace="", status=""))
        self.assertEqual(
            (parsed.namespace_expression, parsed.status_expression), ("Global", "Active")
        )
        self.assertIsNone(parsed.default_mask_length)
        self.assertFalse(parsed.create_prefix)


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_address_is_created(self) -> None:
        out, common = await _run(_config(result_attribute="custom.ip_id"), _context(_device("a")))
        self.assertEqual(out["success"].devices["a"].attribute_bags["custom"]["ip_id"], _IP_ID)
        args, kwargs = common.ensure_ip_address_exists.call_args
        self.assertEqual(args, ("192.168.178.10/24", _NS_ID, _STATUS_ID))
        self.assertFalse(kwargs["add_prefixes_automatically"])
        self.assertTrue(kwargs["use_assigned_ip_if_exists"])
        common.resolve_status_id.assert_called_once_with("Active", content_type="ipam.ipaddress")

    async def test_namespace_and_status_resolved_once_for_all_devices(self) -> None:
        out, common = await _run(_config(), _context(_device("a"), _device("b"), _device("c")))
        self.assertEqual(len(out["success"].devices), 3)
        self.assertEqual(common.resolve_namespace_id.call_count, 1)
        self.assertEqual(common.resolve_status_id.call_count, 1)

    async def test_address_from_attribute(self) -> None:
        dev = _device("a", attribute_bags={"custom": {"new_ip": "192.168.178.20/24"}})
        out, common = await _run(_config(ip_address="{custom.new_ip}"), _context(dev))
        self.assertIn("a", out["success"].devices)
        self.assertEqual(common.ensure_ip_address_exists.call_args.args[0], "192.168.178.20/24")

    async def test_bare_address_takes_mask_from_most_specific_prefix(self) -> None:
        rest = _containing((_PREFIX_ID, "192.168.178.0/24"), ("x", "192.168.0.0/16"))
        out, common = await _run(
            _config(ip_address="192.168.178.10"), _context(_device("a")), rest=rest
        )
        self.assertIn("a", out["success"].devices)
        self.assertEqual(common.ensure_ip_address_exists.call_args.args[0], "192.168.178.10/24")

    async def test_bare_address_without_prefix_fails(self) -> None:
        out, common = await _run(
            _config(ip_address="192.168.178.10"), _context(_device("a")), rest=_containing()
        )
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "prefix_not_found")
        common.ensure_ip_address_exists.assert_not_called()

    async def test_bare_address_without_prefix_uses_default_mask_when_creating(self) -> None:
        out, common = await _run(
            _config(ip_address="192.168.178.10", create_prefix=True, default_mask_length=26),
            _context(_device("a")),
            rest=_containing(),
        )
        self.assertIn("a", out["success"].devices)
        args, kwargs = common.ensure_ip_address_exists.call_args
        self.assertEqual(args[0], "192.168.178.10/26")
        self.assertTrue(kwargs["add_prefixes_automatically"])

    async def test_default_mask_for_ipv6_is_64(self) -> None:
        _, common = await _run(
            _config(ip_address="2001:db8::5", create_prefix=True),
            _context(_device("a")),
            rest=_containing(),
        )
        self.assertEqual(common.ensure_ip_address_exists.call_args.args[0], "2001:db8::5/64")

    async def test_invalid_address_fails_device(self) -> None:
        out, common = await _run(_config(ip_address="not-an-ip"), _context(_device("a")))
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "ip_invalid")
        common.ensure_ip_address_exists.assert_not_called()

    async def test_unresolved_expression_fails_only_that_device(self) -> None:
        good = _device("good", attribute_bags={"custom": {"ip": "10.1.1.1/24"}})
        out, _ = await _run(_config(ip_address="{custom.ip}"), _context(good, _device("bad")))
        self.assertIn("good", out["success"].devices)
        self.assertEqual(out["failure"].devices["bad"].errors[0].code, "ip_unresolved")

    async def test_description_and_dns_name_are_passed(self) -> None:
        dev = _device("a", attribute_bags={"custom": {"d": "core switch"}})
        _, common = await _run(
            _config(description="{custom.d}", dns_name="sw1.example.org"), _context(dev)
        )
        kwargs = common.ensure_ip_address_exists.call_args.kwargs
        self.assertEqual(
            (kwargs["description"], kwargs["dns_name"]), ("core switch", "sw1.example.org")
        )

    async def test_unknown_status_fails_with_status_code(self) -> None:
        common = MagicMock()
        common.resolve_status_id = AsyncMock(side_effect=ValueError("Status 'x' not found"))
        out, _ = await _run(_config(status="x"), _context(_device("a")), common=common)
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "status_not_found")

    async def test_unknown_namespace_fails_with_namespace_code(self) -> None:
        common = MagicMock()
        common.resolve_namespace_id = AsyncMock(side_effect=ValueError("Namespace 'x' not found"))
        out, _ = await _run(_config(namespace="x"), _context(_device("a")), common=common)
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "namespace_not_found")

    async def test_missing_parent_prefix_error_is_explained(self) -> None:
        common = MagicMock()
        common.ensure_ip_address_exists = AsyncMock(
            side_effect=NautobotAPIError("Cannot create IP: No suitable parent prefix exists")
        )
        out, _ = await _run(_config(), _context(_device("a")), common=common)
        error = out["failure"].devices["a"].errors[0]
        self.assertEqual(error.code, "prefix_not_found")
        self.assertIn("create_prefix", error.message)

    async def test_nautobot_error_is_reduced_to_class_name(self) -> None:
        common = MagicMock()
        common.ensure_ip_address_exists = AsyncMock(side_effect=RuntimeError("token abc123"))
        out, _ = await _run(_config(), _context(_device("a")), common=common)
        error = out["failure"].devices["a"].errors[0]
        self.assertNotIn("abc123", error.message)
        self.assertIsNotNone(error.failure)

    async def test_interface_assignment_and_primary(self) -> None:
        out, common = await _run(
            _config(interface_name="Vlan1", set_primary=True), _context(_device("a"))
        )
        self.assertIn("a", out["success"].devices)
        common.resolve_interface_by_name.assert_called_once_with(_DEVICE_ID, "Vlan1")
        common.assign_ip_to_interface.assert_called_once()
        common.assign_primary_ip_to_device.assert_called_once_with(_DEVICE_ID, _IP_ID)

    async def test_primary_not_set_without_the_option(self) -> None:
        _, common = await _run(_config(interface_name="Vlan1"), _context(_device("a")))
        common.assign_primary_ip_to_device.assert_not_called()

    async def test_interface_not_found_keeps_the_created_ip(self) -> None:
        common = MagicMock()
        common.resolve_interface_by_name = AsyncMock(return_value=None)
        out, common = await _run(
            _config(interface_name="Vlan9", result_attribute="custom.ip_id"),
            _context(_device("a")),
            common=common,
        )
        device = out["failure"].devices["a"]
        self.assertEqual(device.errors[0].code, "interface_not_found")
        self.assertIn(_IP_ID, device.errors[0].message)
        self.assertEqual(device.attribute_bags["custom"]["ip_id"], _IP_ID)
        common.assign_ip_to_interface.assert_not_called()

    async def test_device_not_in_nautobot(self) -> None:
        out, _ = await _run(_config(interface_name="Vlan1"), _context(_device("a")), device_id=None)
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "device_not_in_nautobot")

    async def test_input_devices_not_mutated(self) -> None:
        dev = _device("a")
        await _run(_config(result_attribute="custom.ip_id"), _context(dev))
        self.assertEqual(dev.attribute_bags, {})

    async def test_no_devices_makes_no_calls(self) -> None:
        out, common = await _run(_config(), _context())
        self.assertEqual(out["success"].devices, {})
        common.resolve_namespace_id.assert_not_called()

    async def test_counts_in_metadata(self) -> None:
        out, _ = await _run(_config(), _context(_device("a")))
        self.assertEqual(out["success"].metadata["n1.add_ip_counts"], {"success": 1, "failure": 0})


if __name__ == "__main__":
    unittest.main()

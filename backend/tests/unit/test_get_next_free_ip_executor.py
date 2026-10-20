"""Tests for workflow_steps/get_next_free_ip/executor.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from workflow_steps.get_next_free_ip import executor as mod
from workflow_steps.get_next_free_ip.executor import _parse_config, execute

_NS_ID = "11111111-1111-1111-1111-111111111111"
_PREFIX_ID = "22222222-2222-2222-2222-222222222222"


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
        "prefix": "192.168.178.0/24",
        "namespace": "Global",
        "count": 1,
        "start_offset": 1,
        "attribute_path": "custom.new_ip",
    }
    cfg.update(overrides)
    return cfg


def _avail(*hosts: int) -> list[dict]:
    return [{"ip_version": 4, "address": f"192.168.178.{h}/24"} for h in hosts]


def _rest(*, namespaces=None, prefixes=None, available=None):
    """A rest_request stub answering the three lookups in order of the endpoint."""

    async def handler(*, endpoint: str, credentials, method: str = "GET", data=None):
        if endpoint.startswith("ipam/namespaces/"):
            return {"results": [{"id": _NS_ID}] if namespaces is None else namespaces}
        if endpoint.startswith("ipam/prefixes/?"):
            return {"results": [{"id": _PREFIX_ID}] if prefixes is None else prefixes}
        if endpoint.startswith(f"ipam/prefixes/{_PREFIX_ID}/available-ips/"):
            return _avail(1, 2, 3, 4, 5) if available is None else available
        raise AssertionError(f"unexpected endpoint {endpoint}")

    return handler


async def _run(config: dict, context: WorkflowContext, rest=None):
    service = MagicMock()
    service.rest_request = AsyncMock(side_effect=rest or _rest())
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


def _value(device: DeviceContext, key: str = "new_ip"):
    return device.attribute_bags["custom"][key]


class ParseConfigTests(unittest.TestCase):
    def test_missing_source(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(nautobot_source_id=""))

    def test_missing_prefix(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(prefix=" "))

    def test_missing_attribute_path(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(attribute_path=""))

    def test_reserved_attribute_path(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(attribute_path="parsed.ip"))

    def test_read_only_device_field(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(attribute_path="device.id"))

    def test_count_bounds(self) -> None:
        for bad in (0, 101, "x"):
            with self.assertRaises(ValueError):
                _parse_config(_config(count=bad))

    def test_fractional_count_is_refused_not_truncated(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(count=1.9))

    def test_negative_offset(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(start_offset=-1))

    def test_defaults(self) -> None:
        parsed = _parse_config(_config(namespace="", count=None, start_offset=None))
        self.assertEqual(parsed.namespace_expression, "Global")
        self.assertEqual((parsed.count, parsed.start_offset), (1, 1))


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_ip_is_a_string(self) -> None:
        out, service = await _run(_config(), _context(_device("a")))
        self.assertEqual(_value(out["success"].devices["a"]), "192.168.178.1")
        self.assertEqual(out["failure"].devices, {})
        endpoints = [c.kwargs["endpoint"] for c in service.rest_request.call_args_list]
        self.assertIn("namespace=" + _NS_ID, endpoints[1])
        self.assertIn("prefix=192.168.178.0%2F24", endpoints[1])
        self.assertIn("limit=2", endpoints[2])

    async def test_count_gives_a_list(self) -> None:
        out, _ = await _run(_config(count=2), _context(_device("a")))
        self.assertEqual(_value(out["success"].devices["a"]), ["192.168.178.1", "192.168.178.2"])

    async def test_devices_get_distinct_addresses_in_order(self) -> None:
        ctx = _context(_device("a"), _device("b"), _device("c"))
        out, service = await _run(_config(count=2), ctx)
        self.assertEqual(_value(out["success"].devices["a"]), ["192.168.178.1", "192.168.178.2"])
        self.assertEqual(_value(out["success"].devices["b"]), ["192.168.178.3", "192.168.178.4"])
        # The third device needs two but only one is left.
        self.assertIn("c", out["failure"].devices)
        self.assertEqual(out["failure"].devices["c"].errors[0].code, "not_enough_free_ips")
        self.assertEqual(out["failure"].devices["c"].status, DeviceStatus.FAILED)
        self.assertEqual(service.rest_request.call_count, 3)

    async def test_start_offset_skips_lower_addresses(self) -> None:
        rest = _rest(available=_avail(3, 9, 10, 11))
        out, _ = await _run(_config(start_offset=10), _context(_device("a")), rest)
        self.assertEqual(_value(out["success"].devices["a"]), "192.168.178.10")

    async def test_prefix_and_namespace_from_attributes(self) -> None:
        dev = _device(
            "a",
            attribute_bags={"custom": {"net": "192.168.178.0/24", "ns": "Lab"}},
        )
        out, service = await _run(
            _config(prefix="{custom.net}", namespace="{custom.ns}"), _context(dev)
        )
        self.assertIn("a", out["success"].devices)
        first = service.rest_request.call_args_list[0].kwargs["endpoint"]
        self.assertIn("name=Lab", first)

    async def test_unresolved_prefix_expression_fails_device_only(self) -> None:
        good = _device("good", attribute_bags={"custom": {"net": "192.168.178.0/24"}})
        bad = _device("bad")
        out, _ = await _run(_config(prefix="{custom.net}"), _context(good, bad))
        self.assertIn("good", out["success"].devices)
        self.assertEqual(out["failure"].devices["bad"].errors[0].code, "prefix_unresolved")

    async def test_invalid_prefix_text_fails_device(self) -> None:
        out, service = await _run(_config(prefix="not-a-prefix"), _context(_device("a")))
        error = out["failure"].devices["a"].errors[0]
        self.assertEqual(error.code, "prefix_invalid")
        self.assertIn("not-a-prefix", error.message)
        self.assertIn("prefix setting", error.message)
        service.rest_request.assert_not_called()

    async def test_bare_device_address_uses_most_specific_containing_prefix(self) -> None:
        other = "33333333-3333-3333-3333-333333333333"
        rest = _rest(
            prefixes=[
                {"id": other, "prefix": "192.168.0.0/16"},
                {"id": _PREFIX_ID, "prefix": "192.168.178.0/24"},
            ]
        )
        out, service = await _run(
            _config(prefix="{device.primary_ip4}"),
            _context(_device("a", primary_ip4="192.168.178.240/24")),
            rest,
        )
        self.assertEqual(_value(out["success"].devices["a"]), "192.168.178.1")
        lookup = service.rest_request.call_args_list[1].kwargs["endpoint"]
        self.assertIn("contains=192.168.178.240", lookup)
        self.assertIn("namespace=" + _NS_ID, lookup)

    async def test_bare_address_without_containing_prefix_fails(self) -> None:
        out, _ = await _run(
            _config(prefix="{device.primary_ip4}"), _context(_device("a")), _rest(prefixes=[])
        )
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "prefix_not_found")

    async def test_device_cidr_resolves_to_its_network(self) -> None:
        free = [{"ip_version": 4, "address": "10.0.0.7/24"}]
        out, service = await _run(
            _config(prefix="{device.primary_ip4_cidr}"),
            _context(_device("a")),
            _rest(available=free),
        )
        self.assertEqual(_value(out["success"].devices["a"]), "10.0.0.7")
        lookup = service.rest_request.call_args_list[1].kwargs["endpoint"]
        self.assertIn("prefix=10.0.0.0%2F24", lookup)

    async def test_unknown_namespace_fails(self) -> None:
        out, _ = await _run(_config(), _context(_device("a")), _rest(namespaces=[]))
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "namespace_not_found")

    async def test_namespace_uuid_is_not_looked_up(self) -> None:
        out, service = await _run(_config(namespace=_NS_ID), _context(_device("a")))
        self.assertIn("a", out["success"].devices)
        endpoints = [c.kwargs["endpoint"] for c in service.rest_request.call_args_list]
        self.assertFalse(any(e.startswith("ipam/namespaces/") for e in endpoints))

    async def test_prefix_not_found(self) -> None:
        out, _ = await _run(_config(), _context(_device("a")), _rest(prefixes=[]))
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "prefix_not_found")

    async def test_prefix_ambiguous(self) -> None:
        rest = _rest(prefixes=[{"id": _PREFIX_ID}, {"id": "other"}])
        out, _ = await _run(_config(), _context(_device("a")), rest)
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "prefix_ambiguous")

    async def test_spellings_of_one_prefix_share_one_pool(self) -> None:
        # Two raw spellings, one Nautobot prefix: the devices must not both start at the front.
        a = _device("a", attribute_bags={"custom": {"net": "2001:db8::/64"}})
        b = _device("b", attribute_bags={"custom": {"net": "2001:DB8::/64"}})
        avail = [{"ip_version": 6, "address": f"2001:db8::{h}/64"} for h in (1, 2)]
        out, service = await _run(
            _config(prefix="{custom.net}"), _context(a, b), _rest(available=avail)
        )
        self.assertEqual(_value(out["success"].devices["a"]), "2001:db8::1")
        self.assertEqual(_value(out["success"].devices["b"]), "2001:db8::2")
        reads = [
            c
            for c in service.rest_request.call_args_list
            if "available-ips" in c.kwargs["endpoint"]
        ]
        self.assertEqual(len(reads), 1)

    async def test_namespace_name_and_uuid_share_one_pool(self) -> None:
        a = _device("a", attribute_bags={"custom": {"ns": "Global"}})
        b = _device("b", attribute_bags={"custom": {"ns": _NS_ID.upper()}})
        out, _ = await _run(_config(namespace="{custom.ns}"), _context(a, b))
        self.assertEqual(_value(out["success"].devices["a"]), "192.168.178.1")
        self.assertEqual(_value(out["success"].devices["b"]), "192.168.178.2")

    async def test_window_cut_is_not_reported_as_exhausted(self) -> None:
        full = [
            {"ip_version": 4, "address": f"10.0.{i // 250}.{i % 250 + 1}/16"} for i in range(1000)
        ]
        rest = _rest(available=full)
        cfg = _config(prefix="10.0.0.0/16", count=100)
        devices = [_device(f"d{i}") for i in range(11)]
        out, _ = await _run(cfg, _context(*devices), rest)
        self.assertEqual(len(out["success"].devices), 10)
        self.assertEqual(out["failure"].devices["d10"].errors[0].code, "free_ip_window_exceeded")

    async def test_real_exhaustion_still_reported_as_such(self) -> None:
        out, _ = await _run(_config(count=9), _context(_device("a")))
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "not_enough_free_ips")

    async def test_namespace_with_more_rows_is_ambiguous(self) -> None:
        rest = _rest(namespaces=[{"id": _NS_ID}, {"id": _PREFIX_ID}])
        out, _ = await _run(_config(), _context(_device("a")), rest)
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "namespace_ambiguous")

    async def test_prefix_id_that_is_not_a_uuid_is_refused(self) -> None:
        out, service = await _run(
            _config(), _context(_device("a")), _rest(prefixes=[{"id": "../../x"}])
        )
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "invalid_response")
        self.assertFalse(
            any(
                "available-ips" in c.kwargs["endpoint"] for c in service.rest_request.call_args_list
            )
        )

    async def test_unexpected_available_body_fails(self) -> None:
        out, _ = await _run(_config(), _context(_device("a")), _rest(available={"detail": "x"}))
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "invalid_response")

    async def test_nautobot_error_is_reduced_to_class_name(self) -> None:
        async def boom(*, endpoint, credentials, method="GET", data=None):
            raise RuntimeError("token abc123 leaked")

        out, _ = await _run(_config(), _context(_device("a")), boom)
        error = out["failure"].devices["a"].errors[0]
        self.assertNotIn("abc123", error.message)
        self.assertIsNotNone(error.failure)

    async def test_input_devices_not_mutated(self) -> None:
        dev = _device("a")
        await _run(_config(), _context(dev))
        self.assertEqual(dev.attribute_bags, {})
        self.assertEqual(dev.errors, [])

    async def test_no_devices_makes_no_calls(self) -> None:
        out, service = await _run(_config(), _context())
        self.assertEqual(out["success"].devices, {})
        service.rest_request.assert_not_called()

    async def test_counts_in_metadata(self) -> None:
        out, _ = await _run(_config(), _context(_device("a")))
        self.assertEqual(out["success"].metadata["n1.free_ip_counts"], {"success": 1, "failure": 0})


if __name__ == "__main__":
    unittest.main()

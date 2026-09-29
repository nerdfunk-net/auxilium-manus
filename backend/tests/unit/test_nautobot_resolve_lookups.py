"""Tests for the strategy-specific Nautobot device lookups in
workflow_steps/common/nautobot_resolve.py (used by exists-in-nautobot)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from workflow_steps.common.nautobot_resolve import (
    find_device_id_by_interface_ip,
    find_device_id_by_name,
    find_device_id_by_primary_ip,
    strip_ip_mask,
)

_UUID = "efce2684-f64d-4d27-9030-f0e71b1e45c0"


def _service(response: dict) -> MagicMock:
    service = MagicMock()
    service.graphql_query = AsyncMock(return_value=response)
    return service


class StripIpMaskTests(unittest.TestCase):
    def test_strips_mask(self) -> None:
        self.assertEqual(strip_ip_mask("10.0.0.1/24"), "10.0.0.1")

    def test_bare_address_and_whitespace(self) -> None:
        self.assertEqual(strip_ip_mask(" 10.0.0.1 "), "10.0.0.1")


class FindByNameTests(unittest.IsolatedAsyncioTestCase):
    async def test_found_prefers_exact_match(self) -> None:
        service = _service(
            {"data": {"devices": [{"id": "x", "name": "R1-old"}, {"id": _UUID, "name": "R1"}]}}
        )
        result = await find_device_id_by_name(
            nautobot_service=service, credentials=MagicMock(), name="R1"
        )
        self.assertEqual(result, _UUID)

    async def test_not_found(self) -> None:
        service = _service({"data": {"devices": []}})
        result = await find_device_id_by_name(
            nautobot_service=service, credentials=MagicMock(), name="R1"
        )
        self.assertIsNone(result)

    async def test_case_insensitive_uses_ie_filter(self) -> None:
        service = _service({"data": {"devices": [{"id": _UUID, "name": "r1"}]}})
        result = await find_device_id_by_name(
            nautobot_service=service,
            credentials=MagicMock(),
            name="R1",
            case_insensitive=True,
        )
        self.assertEqual(result, _UUID)
        self.assertIn("name__ie", service.graphql_query.call_args.args[0])


def _ip_response(*entries: tuple[str, list[dict]]) -> dict:
    """Real Nautobot shape for `ip_addresses(address:) { address primary_ip4_for {...} }`."""
    return {
        "data": {
            "ip_addresses": [
                {"address": address, "primary_ip4_for": devices} for address, devices in entries
            ]
        }
    }


class FindByPrimaryIpTests(unittest.IsolatedAsyncioTestCase):
    async def test_found_strips_mask_and_reads_primary_ip4_for(self) -> None:
        # A bare host matches the stored IP whatever its mask (Nautobot `net_in`),
        # so the mask is dropped; `primary_ip4_for` restricts to primary IPs.
        service = _service(_ip_response(("192.168.178.1/24", [{"id": _UUID, "name": "lab-001"}])))
        result = await find_device_id_by_primary_ip(
            nautobot_service=service, credentials=MagicMock(), ip_address="192.168.178.1/24"
        )
        self.assertEqual(result, _UUID)
        query, variables, _ = service.graphql_query.call_args.args
        self.assertIn("ip_addresses(address:", query)
        self.assertIn("primary_ip4_for", query)
        self.assertNotIn("devices(", query)
        self.assertEqual(variables, {"address": ["192.168.178.1"]})

    async def test_ip_on_an_interface_but_not_primary_is_not_found(self) -> None:
        service = _service(_ip_response(("192.168.179.1/24", [])))
        result = await find_device_id_by_primary_ip(
            nautobot_service=service, credentials=MagicMock(), ip_address="192.168.179.1"
        )
        self.assertIsNone(result)

    async def test_first_ip_that_is_primary_wins(self) -> None:
        # Same host can exist in several namespaces; only one may be a primary.
        service = _service(
            _ip_response(
                ("10.0.0.1/24", []),
                ("10.0.0.1/32", [{"id": _UUID, "name": "r1"}]),
            )
        )
        result = await find_device_id_by_primary_ip(
            nautobot_service=service, credentials=MagicMock(), ip_address="10.0.0.1"
        )
        self.assertEqual(result, _UUID)

    async def test_unknown_ip_is_not_found(self) -> None:
        service = _service({"data": {"ip_addresses": []}})
        result = await find_device_id_by_primary_ip(
            nautobot_service=service, credentials=MagicMock(), ip_address="10.0.0.1"
        )
        self.assertIsNone(result)

    async def test_graphql_errors_are_not_found_and_logged(self) -> None:
        service = _service({"errors": [{"message": "boom"}], "data": None})
        with self.assertLogs("workflow_steps.common.nautobot_resolve", level="WARNING"):
            result = await find_device_id_by_primary_ip(
                nautobot_service=service, credentials=MagicMock(), ip_address="10.0.0.1"
            )
        self.assertIsNone(result)


class FindByInterfaceIpTests(unittest.IsolatedAsyncioTestCase):
    async def test_found(self) -> None:
        service = _service(
            {
                "data": {
                    "ip_addresses": [
                        {
                            "interface_assignments": [
                                {"interface": {"device": {"id": _UUID, "name": "LAB"}}}
                            ]
                        }
                    ]
                }
            }
        )
        result = await find_device_id_by_interface_ip(
            nautobot_service=service, credentials=MagicMock(), ip_address="192.168.178.120/24"
        )
        self.assertEqual(result, _UUID)
        query, variables, _ = service.graphql_query.call_args.args
        self.assertIn("interface_assignments", query)
        self.assertEqual(variables, {"address": ["192.168.178.120"]})

    async def test_ip_exists_but_unassigned(self) -> None:
        service = _service({"data": {"ip_addresses": [{"interface_assignments": []}]}})
        result = await find_device_id_by_interface_ip(
            nautobot_service=service, credentials=MagicMock(), ip_address="10.0.0.1"
        )
        self.assertIsNone(result)

    async def test_no_ip_address_object(self) -> None:
        service = _service({"data": {"ip_addresses": []}})
        result = await find_device_id_by_interface_ip(
            nautobot_service=service, credentials=MagicMock(), ip_address="10.0.0.1"
        )
        self.assertIsNone(result)

    async def test_null_nested_values_are_skipped(self) -> None:
        service = _service(
            {
                "data": {
                    "ip_addresses": [
                        {
                            "interface_assignments": [
                                {"interface": None},
                                {"interface": {"device": None}},
                                {"interface": {"device": {"id": _UUID, "name": "LAB"}}},
                            ]
                        }
                    ]
                }
            }
        )
        result = await find_device_id_by_interface_ip(
            nautobot_service=service, credentials=MagicMock(), ip_address="10.0.0.1"
        )
        self.assertEqual(result, _UUID)


if __name__ == "__main__":
    unittest.main()

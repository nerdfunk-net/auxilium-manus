"""Tests for services/sources/nautobot/source_service.py orchestration."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from models.sources_nautobot import DeviceInfo, LogicalOperation
from services.nautobot.credentials import NautobotCredentials
from services.sources.nautobot.source_service import NautobotSourceService

_CREDS = NautobotCredentials(url="http://nb.test", token="tok")


def _dev(did: str) -> DeviceInfo:
    return DeviceInfo(id=did, name=did)


def _service() -> NautobotSourceService:
    svc = NautobotSourceService(MagicMock(), _CREDS, persistence_service=MagicMock())
    svc.query_service = MagicMock()
    svc.query_service._query_all_devices = AsyncMock(return_value=[_dev("a"), _dev("b"), _dev("c")])
    svc.query_service._query_devices_by_name = AsyncMock(return_value=[_dev("a"), _dev("b")])
    svc.query_service.refresh_bulk_cache = AsyncMock(return_value=7)
    svc.evaluator = MagicMock()
    svc.evaluator._execute_operation = AsyncMock()
    svc.export_service = MagicMock()
    svc.export_service.analyze_devices = AsyncMock(return_value={"device_count": 2})
    svc.device_query_service = MagicMock()
    svc.device_query_service.get_device_details = AsyncMock(return_value={"id": "a", "name": "a"})
    svc.device_query_service.get_device_attributes = AsyncMock(return_value={"nautobot": {}})
    svc.metadata_service = MagicMock()
    svc.metadata_service.get_custom_fields = AsyncMock(return_value=[{"name": "cf"}])
    svc.metadata_service.get_field_values = AsyncMock(return_value=[{"value": "x"}])
    return svc


_TREE = [{"version": 2, "tree": {"internalLogic": "AND", "items": [
    {"field": "role", "operator": "equals", "value": "leaf"}
]}}]


class PreviewInventoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_operations_returns_all_devices(self) -> None:
        svc = _service()
        devices, count = await svc.preview_inventory([])
        self.assertEqual({d.id for d in devices}, {"a", "b", "c"})
        self.assertEqual(count, 0)

    async def test_single_operation_result(self) -> None:
        svc = _service()
        svc.evaluator._execute_operation.return_value = (
            {"a", "b"}, 2, {"a": _dev("a"), "b": _dev("b")}
        )
        op = LogicalOperation(operation_type="AND")
        devices, count = await svc.preview_inventory([op])
        self.assertEqual({d.id for d in devices}, {"a", "b"})
        self.assertEqual(count, 2)

    async def test_and_then_not_combination(self) -> None:
        svc = _service()
        svc.evaluator._execute_operation.side_effect = [
            ({"a", "b", "c"}, 1, {i: _dev(i) for i in "abc"}),
            ({"c"}, 1, {"c": _dev("c")}),
        ]
        ops = [
            LogicalOperation(operation_type="AND"),
            LogicalOperation(operation_type="NOT"),
        ]
        devices, _ = await svc.preview_inventory(ops)
        self.assertEqual({d.id for d in devices}, {"a", "b"})

    async def test_leading_not_operation_yields_empty(self) -> None:
        svc = _service()
        svc.evaluator._execute_operation.return_value = ({"a"}, 1, {"a": _dev("a")})
        devices, _ = await svc.preview_inventory([LogicalOperation(operation_type="NOT")])
        self.assertEqual(devices, [])


class DelegationTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_devices_by_ids_filters(self) -> None:
        devices = await _service().resolve_devices_by_ids(["a", "c", "zzz"])
        self.assertEqual({d.id for d in devices}, {"a", "c"})

    async def test_search_devices_by_name_applies_limit(self) -> None:
        svc = _service()
        result = await svc.search_devices_by_name("r", limit=1)
        self.assertEqual(len(result), 1)

    async def test_simple_delegations(self) -> None:
        svc = _service()
        self.assertEqual(await svc.get_device_details("a"), {"id": "a", "name": "a"})
        self.assertEqual(await svc.get_device_attributes("a"), {"nautobot": {}})
        self.assertEqual(await svc.refresh_bulk_device_cache(), 7)
        self.assertEqual(await svc.get_custom_fields(), [{"name": "cf"}])
        self.assertEqual(await svc.get_field_values("role"), [{"value": "x"}])


class AnalyzeInventoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_persistence_service(self) -> None:
        svc = _service()
        svc._persistence_service = None
        with self.assertRaises(ValueError):
            await svc.analyze_inventory(1, "alice")

    async def test_inventory_not_found(self) -> None:
        svc = _service()
        svc._persistence_service.get_inventory.return_value = None
        with self.assertRaises(ValueError):
            await svc.analyze_inventory(1, "alice")

    async def test_static_inventory_without_ids_returns_empty_analysis(self) -> None:
        svc = _service()
        svc._persistence_service.get_inventory.return_value = {
            "inventory_type": "static", "device_ids": []
        }
        out = await svc.analyze_inventory(1, "alice")
        self.assertEqual(out["device_count"], 0)

    async def test_static_inventory_with_ids_calls_export(self) -> None:
        svc = _service()
        svc._persistence_service.get_inventory.return_value = {
            "inventory_type": "static", "device_ids": ["a"]
        }
        out = await svc.analyze_inventory(1, "alice")
        self.assertEqual(out, {"device_count": 2})
        svc.export_service.analyze_devices.assert_awaited_once()

    async def test_dynamic_inventory_converts_and_previews(self) -> None:
        svc = _service()
        svc._persistence_service.get_inventory.return_value = {
            "inventory_type": "filter", "conditions": _TREE
        }
        svc.evaluator._execute_operation.return_value = ({"a"}, 1, {"a": _dev("a")})
        out = await svc.analyze_inventory(1, "alice")
        self.assertEqual(out, {"device_count": 2})


class ResolveSavedInventoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_ids_static(self) -> None:
        out = await _service().resolve_saved_inventory_ids(
            {"inventory_type": "static", "device_ids": ["a", "b"], "name": "n"}, 5
        )
        self.assertEqual(out["device_count"], 2)
        self.assertEqual(out["inventory_id"], 5)

    async def test_resolve_ids_static_empty(self) -> None:
        out = await _service().resolve_saved_inventory_ids(
            {"inventory_type": "static", "device_ids": [], "name": "n"}, 5
        )
        self.assertEqual(out["device_ids"], [])

    async def test_resolve_ids_dynamic_no_conditions(self) -> None:
        out = await _service().resolve_saved_inventory_ids(
            {"inventory_type": "filter", "conditions": [], "name": "n"}, 5
        )
        self.assertEqual(out["device_count"], 0)

    async def test_resolve_ids_dynamic(self) -> None:
        svc = _service()
        svc.evaluator._execute_operation.return_value = (
            {"a", "b"}, 1, {"a": _dev("a"), "b": _dev("b")}
        )
        out = await svc.resolve_saved_inventory_ids(
            {"inventory_type": "filter", "conditions": _TREE, "name": "n"}, 5
        )
        self.assertEqual(out["device_count"], 2)

    async def test_resolve_detailed_dynamic_with_error_device(self) -> None:
        svc = _service()
        svc.evaluator._execute_operation.return_value = (
            {"a", "b"}, 1, {"a": _dev("a"), "b": _dev("b")}
        )
        svc.device_query_service.get_device_details = AsyncMock(
            side_effect=[{"id": "a", "name": "a", "primary_ip4": {"address": "10.0.0.1/24"}},
                         RuntimeError("boom")]
        )
        out = await svc.resolve_saved_inventory_detailed(
            {"inventory_type": "filter", "conditions": _TREE, "name": "n"}, 5
        )
        self.assertEqual(out["device_count"], 1)
        self.assertEqual(out["devices"][0]["primary_ip4"], "10.0.0.1/24")

    async def test_resolve_detailed_static_empty(self) -> None:
        out = await _service().resolve_saved_inventory_detailed(
            {"inventory_type": "static", "device_ids": [], "name": "n"}, 5
        )
        self.assertEqual(out["device_details"], [])

    async def test_resolve_devices_response_static(self) -> None:
        resp = await _service().resolve_saved_inventory_devices(
            {"inventory_type": "static", "device_ids": ["a"], "name": "n"}
        )
        self.assertEqual(resp.total_count, 1)
        self.assertEqual(resp.operations_executed, 0)

    async def test_resolve_devices_response_dynamic_no_conditions(self) -> None:
        resp = await _service().resolve_saved_inventory_devices(
            {"inventory_type": "filter", "conditions": []}
        )
        self.assertEqual(resp.total_count, 0)


if __name__ == "__main__":
    unittest.main()

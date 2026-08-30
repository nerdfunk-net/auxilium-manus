"""Tests for services/sources/nautobot/evaluator.py against a mocked query service."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from models.sources_nautobot import DeviceInfo, LogicalCondition, LogicalOperation
from services.sources.nautobot.evaluator import (
    NautobotSourceEvaluator,
    _combine_logical_results,
    _operator_flags,
    _pack_devices,
    _subtract_not_results,
)


def _dev(did: str, **kw) -> DeviceInfo:
    return DeviceInfo(id=did, name=kw.pop("name", did), **kw)


class PureHelperTests(unittest.TestCase):
    def test_operator_flags(self) -> None:
        self.assertEqual(_operator_flags("contains"), (True, False))
        self.assertEqual(_operator_flags("not_contains"), (True, True))
        self.assertEqual(_operator_flags("not_equals"), (False, True))
        self.assertEqual(_operator_flags("equals"), (False, False))

    def test_pack_devices(self) -> None:
        ids, count, dmap = _pack_devices([_dev("a"), _dev("b")], operations_count=3)
        self.assertEqual(ids, {"a", "b"})
        self.assertEqual(count, 3)
        self.assertEqual(set(dmap), {"a", "b"})

    def test_subtract_not_results(self) -> None:
        self.assertEqual(
            _subtract_not_results({"a", "b", "c"}, [{"b"}, {"c"}]), {"a"}
        )

    def test_combine_and_or_not(self) -> None:
        def intersect(sets: list[set]) -> set:
            return set.intersection(*sets) if sets else set()

        def union(sets: list[set]) -> set:
            return set().union(*sets) if sets else set()

        self.assertEqual(
            _combine_logical_results(
                operation_type="AND",
                condition_results=[{"a", "b"}, {"b", "c"}],
                not_results=[{"b"}],
                intersect=intersect,
                union=union,
            ),
            set(),
        )
        self.assertEqual(
            _combine_logical_results(
                operation_type="or",
                condition_results=[{"a"}, {"b"}],
                not_results=[],
                intersect=intersect,
                union=union,
            ),
            {"a", "b"},
        )
        self.assertEqual(
            _combine_logical_results(
                operation_type="NOT",
                condition_results=[{"a"}],
                not_results=[],
                intersect=intersect,
                union=union,
            ),
            {"a"},
        )
        self.assertEqual(
            _combine_logical_results(
                operation_type="bogus",
                condition_results=[{"a"}],
                not_results=[],
                intersect=intersect,
                union=union,
            ),
            set(),
        )


def _query_service() -> MagicMock:
    qs = MagicMock()
    for name in (
        "_query_devices_by_name",
        "_query_devices_by_location",
        "_query_devices_by_role",
        "_query_devices_by_status",
        "_query_devices_by_tag",
        "_query_devices_by_devicetype",
        "_query_devices_by_manufacturer",
        "_query_devices_by_platform",
        "_query_devices_by_has_primary",
        "_query_devices_by_ip_prefix",
        "_query_devices_by_primary_prefix",
        "_query_devices_by_custom_field",
        "_query_all_devices",
    ):
        setattr(qs, name, AsyncMock(return_value=[]))
    return qs


class EvaluatorConditionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.qs = _query_service()
        self.evaluator = NautobotSourceEvaluator(self.qs)

    async def test_empty_condition_is_skipped(self) -> None:
        ids, count, _ = await self.evaluator._execute_condition(
            LogicalCondition(field="", operator="equals", value="")
        )
        self.assertEqual((ids, count), (set(), 0))

    async def test_mapped_field_exact_match(self) -> None:
        self.qs._query_devices_by_status.return_value = [_dev("a"), _dev("b")]
        ids, _, dmap = await self.evaluator._execute_condition(
            LogicalCondition(field="status", operator="equals", value="active")
        )
        self.assertEqual(ids, {"a", "b"})
        self.assertEqual(set(dmap), {"a", "b"})

    async def test_name_contains_passes_use_contains(self) -> None:
        self.qs._query_devices_by_name.return_value = [_dev("a")]
        await self.evaluator._execute_condition(
            LogicalCondition(field="name", operator="contains", value="rtr")
        )
        self.qs._query_devices_by_name.assert_awaited_with("rtr", use_contains=True)

    async def test_unknown_field_returns_empty(self) -> None:
        ids, count, _ = await self.evaluator._execute_condition(
            LogicalCondition(field="nonsense", operator="equals", value="x")
        )
        self.assertEqual((ids, count), (set(), 0))

    async def test_ip_prefix_field_routes_to_prefix_query(self) -> None:
        self.qs._query_devices_by_ip_prefix.return_value = [_dev("a")]
        ids, _, _ = await self.evaluator._execute_condition(
            LogicalCondition(field="ip_prefix", operator="equals", value="10.0.0.0/24")
        )
        self.assertEqual(ids, {"a"})
        self.qs._query_devices_by_ip_prefix.assert_awaited_once()

    async def test_custom_field_condition_with_negation(self) -> None:
        self.qs._query_devices_by_custom_field.return_value = [_dev("a")]
        self.qs._query_all_devices.return_value = [_dev("a"), _dev("b"), _dev("c")]
        ids, _, _ = await self.evaluator._execute_condition(
            LogicalCondition(field="cf_site", operator="not_equals", value="NYC")
        )
        self.assertEqual(ids, {"b", "c"})

    async def test_native_not_equals_for_role(self) -> None:
        self.qs._query_devices_by_role.return_value = [_dev("a")]
        ids, count, _ = await self.evaluator._execute_condition(
            LogicalCondition(field="role", operator="not_equals", value="mgmt")
        )
        self.assertEqual(ids, {"a"})
        self.qs._query_devices_by_role.assert_awaited_with("mgmt", use_negation=True)

    async def test_client_side_negation_for_platform(self) -> None:
        # platform has no native negation handler -> falls back to client negation
        self.qs._query_devices_by_platform.return_value = [_dev("a")]
        self.qs._query_all_devices.return_value = [_dev("a"), _dev("b")]
        ids, _, _ = await self.evaluator._execute_condition(
            LogicalCondition(field="platform", operator="not_equals", value="ios")
        )
        self.assertEqual(ids, {"b"})

    async def test_condition_exception_is_swallowed(self) -> None:
        self.qs._query_devices_by_status.side_effect = RuntimeError("boom")
        ids, count, _ = await self.evaluator._execute_condition(
            LogicalCondition(field="status", operator="equals", value="active")
        )
        self.assertEqual((ids, count), (set(), 0))


class EvaluatorOperationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.qs = _query_service()
        self.evaluator = NautobotSourceEvaluator(self.qs)

    async def test_and_operation_intersects_conditions(self) -> None:
        self.qs._query_devices_by_role.return_value = [_dev("a"), _dev("b")]
        self.qs._query_devices_by_status.return_value = [_dev("b"), _dev("c")]
        op = LogicalOperation(
            operation_type="AND",
            conditions=[
                LogicalCondition(field="role", operator="equals", value="leaf"),
                LogicalCondition(field="status", operator="equals", value="active"),
            ],
        )
        result, _, _ = await self.evaluator._execute_operation(op)
        self.assertEqual(result, {"b"})

    async def test_nested_not_operation_is_subtracted(self) -> None:
        self.qs._query_devices_by_status.return_value = [_dev("a"), _dev("b"), _dev("c")]
        self.qs._query_devices_by_role.return_value = [_dev("c")]
        op = LogicalOperation(
            operation_type="AND",
            conditions=[LogicalCondition(field="status", operator="equals", value="active")],
            nested_operations=[
                LogicalOperation(
                    operation_type="NOT",
                    conditions=[
                        LogicalCondition(field="role", operator="equals", value="mgmt")
                    ],
                )
            ],
        )
        result, _, _ = await self.evaluator._execute_operation(op)
        self.assertEqual(result, {"a", "b"})


if __name__ == "__main__":
    unittest.main()

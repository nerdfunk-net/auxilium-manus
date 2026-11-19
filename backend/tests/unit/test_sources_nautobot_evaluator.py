"""Tests for services/sources/nautobot/evaluator.py against a mocked query service."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from pydantic import ValidationError

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
        self.assertEqual(self.evaluator.failures, ["unsupported field nonsense"])

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

    async def test_condition_exception_is_swallowed_but_recorded(self) -> None:
        self.qs._query_devices_by_status.side_effect = RuntimeError("boom")
        ids, count, _ = await self.evaluator._execute_condition(
            LogicalCondition(field="status", operator="equals", value="active")
        )
        self.assertEqual((ids, count), (set(), 0))
        self.assertEqual(self.evaluator.failures, ["status equals"])

    async def test_a_real_empty_result_or_skipped_condition_is_not_a_failure(self) -> None:
        self.qs._query_devices_by_status.return_value = []
        await self.evaluator._execute_condition(
            LogicalCondition(field="status", operator="equals", value="active")
        )
        await self.evaluator._execute_condition(
            LogicalCondition(field="", operator="equals", value="")
        )
        self.assertEqual(self.evaluator.failures, [])


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


class LocationIsExactMatchOnlyTests(unittest.IsolatedAsyncioTestCase):
    """Locations support "equals" / "not_equals" only — "Location contains City"
    must never be possible (and so can never match "City A"). Device names and
    custom fields keep their "contains" operator."""

    def setUp(self) -> None:
        self.qs = _query_service()
        self.evaluator = NautobotSourceEvaluator(self.qs)

    async def test_location_equals_is_an_exact_query(self) -> None:
        self.qs._query_devices_by_location.return_value = [_dev("a")]

        ids, _, _ = await self.evaluator._execute_condition(
            LogicalCondition(field="location", operator="equals", value="City")
        )

        self.assertEqual(ids, {"a"})
        self.qs._query_devices_by_location.assert_awaited_once_with("City")

    async def test_location_not_equals_uses_native_negation(self) -> None:
        self.qs._query_devices_by_location.return_value = [_dev("b")]

        ids, _, _ = await self.evaluator._execute_condition(
            LogicalCondition(field="location", operator="not_equals", value="City")
        )

        self.assertEqual(ids, {"b"})
        self.qs._query_devices_by_location.assert_awaited_once_with("City", use_negation=True)

    def test_the_model_rejects_contains_operators_on_location(self) -> None:
        for operator in ("contains", "not_contains"):
            with self.subTest(operator=operator):
                with self.assertRaises(ValidationError) as ctx:
                    LogicalCondition(field="location", operator=operator, value="City")
                self.assertIn("equals", str(ctx.exception))

    def test_the_model_rejects_it_inside_nested_operations_too(self) -> None:
        with self.assertRaises(ValidationError):
            LogicalOperation.model_validate(
                {
                    "operation_type": "AND",
                    "conditions": [{"field": "role", "operator": "equals", "value": "leaf"}],
                    "nested_operations": [
                        {
                            "operation_type": "OR",
                            "conditions": [
                                {"field": "location", "operator": "contains", "value": "City"}
                            ],
                        }
                    ],
                }
            )

    def test_equals_and_not_equals_on_location_are_valid(self) -> None:
        for operator in ("equals", "not_equals"):
            LogicalCondition(field="location", operator=operator, value="City A")

    def test_contains_is_still_valid_for_names_and_custom_fields(self) -> None:
        LogicalCondition(field="name", operator="contains", value="rtr")
        LogicalCondition(field="cf_site_code", operator="not_contains", value="NYC")

    async def test_evaluator_refuses_location_contains_even_if_validation_is_bypassed(
        self,
    ) -> None:
        condition = LogicalCondition.model_construct(
            field="location", operator="contains", value="City"
        )

        ids, count, _ = await self.evaluator._execute_condition(condition)

        self.assertEqual((ids, count), (set(), 0))
        self.qs._query_devices_by_location.assert_not_awaited()

    async def test_name_contains_is_unaffected(self) -> None:
        self.qs._query_devices_by_name.return_value = [_dev("a")]

        ids, _, _ = await self.evaluator._execute_condition(
            LogicalCondition(field="name", operator="contains", value="rtr")
        )

        self.assertEqual(ids, {"a"})
        self.qs._query_devices_by_name.assert_awaited_with("rtr", use_contains=True)

    async def test_name_equals_is_unaffected(self) -> None:
        await self.evaluator._execute_condition(
            LogicalCondition(field="name", operator="equals", value="rtr1")
        )

        self.qs._query_devices_by_name.assert_awaited_with("rtr1", use_contains=False)


if __name__ == "__main__":
    unittest.main()


class AllDevicesFieldTests(unittest.IsolatedAsyncioTestCase):
    """``all_devices`` selects the whole fleet so "all devices but City A" can be built:
    ``all_devices AND location not_equals City A``."""

    def setUp(self) -> None:
        self.qs = _query_service()
        self.qs._query_all_devices.return_value = [_dev("a"), _dev("b"), _dev("c")]
        self.evaluator = NautobotSourceEvaluator(self.qs)

    @staticmethod
    def _all() -> LogicalCondition:
        return LogicalCondition(field="all_devices", operator="equals", value="true")

    async def test_all_devices_returns_the_whole_fleet(self) -> None:
        ids, _, dmap = await self.evaluator._execute_condition(self._all())
        self.assertEqual(ids, {"a", "b", "c"})
        self.assertEqual(set(dmap), {"a", "b", "c"})
        self.assertEqual(self.evaluator.failures, [])

    def test_the_model_accepts_only_the_value_true(self) -> None:
        for value in ("", "false", "False", "yes", "TRUE", " true"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError) as ctx:
                    LogicalCondition(field="all_devices", operator="equals", value=value)
                self.assertIn("'true'", str(ctx.exception))

    async def test_and_with_a_not_equals_excludes_that_location(self) -> None:
        self.qs._query_devices_by_location.return_value = [_dev("b"), _dev("c")]
        op = LogicalOperation(
            operation_type="AND",
            conditions=[
                self._all(),
                LogicalCondition(field="location", operator="not_equals", value="City A"),
            ],
        )
        result, _, _ = await self.evaluator._execute_operation(op)
        self.assertEqual(result, {"b", "c"})
        # the exclusion is Nautobot's native location__n, not a client-side subtraction
        self.qs._query_devices_by_location.assert_awaited_once_with("City A", use_negation=True)

    async def test_and_with_a_negated_group_excludes_its_devices(self) -> None:
        self.qs._query_devices_by_location.return_value = [_dev("a")]
        op = LogicalOperation(
            operation_type="AND",
            conditions=[self._all()],
            nested_operations=[
                LogicalOperation(
                    operation_type="NOT",
                    conditions=[
                        LogicalCondition(field="location", operator="equals", value="City A")
                    ],
                )
            ],
        )
        result, _, _ = await self.evaluator._execute_operation(op)
        self.assertEqual(result, {"b", "c"})

    def test_the_model_rejects_all_devices_next_to_other_conditions_under_or(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            LogicalOperation(
                operation_type="OR",
                conditions=[
                    self._all(),
                    LogicalCondition(field="role", operator="equals", value="leaf"),
                ],
            )
        self.assertIn("OR", str(ctx.exception))

    def test_the_model_rejects_an_or_group_that_holds_all_devices_and_more(self) -> None:
        with self.assertRaises(ValidationError):
            LogicalOperation(
                operation_type="AND",
                conditions=[LogicalCondition(field="role", operator="equals", value="leaf")],
                nested_operations=[
                    LogicalOperation(
                        operation_type="or",
                        conditions=[self._all()],
                        nested_operations=[
                            LogicalOperation(
                                operation_type="AND",
                                conditions=[
                                    LogicalCondition(field="role", operator="equals", value="x")
                                ],
                            )
                        ],
                    )
                ],
            )

    async def test_or_with_only_all_devices_and_a_not_is_the_fleet_minus_the_not(self) -> None:
        self.qs._query_devices_by_location.return_value = [_dev("a")]
        op = LogicalOperation(
            operation_type="OR",
            conditions=[self._all()],
            nested_operations=[
                LogicalOperation(
                    operation_type="NOT",
                    conditions=[
                        LogicalCondition(field="location", operator="equals", value="City A")
                    ],
                )
            ],
        )
        result, _, _ = await self.evaluator._execute_operation(op)
        self.assertEqual(result, {"b", "c"})

    def test_the_model_accepts_only_equals(self) -> None:
        self._all()
        for operator in ("not_equals", "contains", "not_contains"):
            with self.subTest(operator=operator):
                with self.assertRaises(ValidationError) as ctx:
                    LogicalCondition(field="all_devices", operator=operator, value="true")
                self.assertIn("all_devices", str(ctx.exception))

"""Logical operation evaluator — AND/OR/NOT device set operations.

Ported from cockpit inventory evaluator with adjusted imports.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from workflow_steps.get_nautobot_devices.models import (
    DeviceInfo,
    LogicalCondition,
    LogicalOperation,
)

if TYPE_CHECKING:
    from workflow_steps.get_nautobot_devices.nautobot.query_service import NautobotQueryService

logger = logging.getLogger(__name__)


class NautobotEvaluator:
    def __init__(self, query_service: NautobotQueryService) -> None:
        self.qs = query_service
        self._field_map = {
            "name": query_service._query_devices_by_name,
            "location": query_service._query_devices_by_location,
            "role": query_service._query_devices_by_role,
            "status": query_service._query_devices_by_status,
            "tag": query_service._query_devices_by_tag,
            "device_type": query_service._query_devices_by_devicetype,
            "manufacturer": query_service._query_devices_by_manufacturer,
            "platform": query_service._query_devices_by_platform,
            "has_primary": query_service._query_devices_by_has_primary,
        }

    async def evaluate(self, operations: list[LogicalOperation]) -> list[DeviceInfo]:
        if not operations:
            return []

        all_data: dict[str, DeviceInfo] = {}
        result_ids: set[str] = set()
        initialized = False

        for op in operations:
            op_ids, _, op_data = await self._execute_operation(op)
            all_data.update(op_data)

            if not initialized:
                result_ids = op_ids
                initialized = True
            else:
                result_ids = result_ids.intersection(op_ids)

        return [all_data[i] for i in result_ids if i in all_data]

    async def _execute_operation(
        self, operation: LogicalOperation
    ) -> tuple[set[str], int, dict[str, DeviceInfo]]:
        ops_count = 0
        all_data: dict[str, DeviceInfo] = {}
        condition_results: list[set[str]] = []
        not_results: list[set[str]] = []

        for condition in operation.conditions:
            ids, count, data = await self._execute_condition(condition)
            condition_results.append(ids)
            ops_count += count
            all_data.update(data)

        for nested in operation.nested_operations:
            nested_ids, nested_count, nested_data = await self._execute_operation(nested)
            ops_count += nested_count
            all_data.update(nested_data)
            if nested.operation_type.upper() == "NOT":
                not_results.append(nested_ids)
            else:
                condition_results.append(nested_ids)

        op_type = operation.operation_type.upper()
        if op_type == "AND":
            result = self._intersect(condition_results)
        elif op_type == "OR":
            result = self._union(condition_results)
        elif op_type == "NOT":
            result = self._union(condition_results)
        else:
            result = set()

        for not_set in not_results:
            result = result.difference(not_set)

        return result, ops_count, all_data

    async def _execute_condition(
        self, condition: LogicalCondition
    ) -> tuple[set[str], int, dict[str, DeviceInfo]]:
        if not condition.field or condition.value is None or condition.value == "":
            return set(), 0, {}

        try:
            if condition.field == "ip_prefix":
                devices = await self.qs._query_devices_by_ip_prefix(
                    condition.value, condition.operator
                )
                return {d.id for d in devices}, 1, {d.id: d for d in devices}

            use_contains = condition.operator in ("contains", "not_contains")
            is_negated = condition.operator in ("not_equals", "not_contains")

            native_negation = {"location", "device_type", "manufacturer", "role"}

            if condition.field in native_negation and condition.operator == "not_equals":
                fn = self._field_map[condition.field]
                devices = await fn(condition.value, use_negation=True)
                return {d.id for d in devices}, 1, {d.id: d for d in devices}

            fn = self._field_map.get(condition.field)
            if fn is None:
                logger.warning("No query function for field: %s", condition.field)
                return set(), 0, {}

            if condition.field in ("name", "location") and use_contains:
                devices = await fn(condition.value, use_contains=True)
            elif condition.field in ("name", "location"):
                devices = await fn(condition.value, use_contains=False)
            else:
                devices = await fn(condition.value)

            if is_negated:
                all_devices = await self.qs._query_all_devices()
                matched = {d.id for d in devices}
                devices = [d for d in all_devices if d.id not in matched]

            return {d.id for d in devices}, 1, {d.id: d for d in devices}

        except Exception:
            logger.exception("Error evaluating condition %s=%s", condition.field, condition.value)
            return set(), 0, {}

    def _intersect(self, sets: list[set[str]]) -> set[str]:
        if not sets:
            return set()
        result = sets[0]
        for s in sets[1:]:
            result = result.intersection(s)
        return result

    def _union(self, sets: list[set[str]]) -> set[str]:
        result: set[str] = set()
        for s in sets:
            result = result.union(s)
        return result

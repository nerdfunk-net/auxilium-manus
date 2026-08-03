"""
Inventory evaluator — logical operation execution for device filtering.

Extracted from InventoryService as part of Phase 4 decomposition.
See: doc/refactoring/REFACTORING_SERVICES.md — Phase 4
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from models.sources_nautobot import DeviceInfo, LogicalCondition, LogicalOperation

if TYPE_CHECKING:
    from services.sources.nautobot.query_service import NautobotSourceQueryService

logger = logging.getLogger(__name__)

_NATIVE_NOT_EQUALS_LOG_SUFFIX = {
    "location": "using GraphQL location__n",
    "device_type": "using GraphQL device_type__n",
    "manufacturer": "using GraphQL manufacturer__n",
    "role": "using GraphQL role__n",
}


def _operator_flags(operator: str) -> tuple[bool, bool]:
    use_contains = operator in ["contains", "not_contains"]
    is_negated = operator in ["not_equals", "not_contains"]
    return use_contains, is_negated


def _pack_devices(
    devices_data: list[DeviceInfo], *, operations_count: int = 1
) -> tuple[set[str], int, dict[str, DeviceInfo]]:
    device_ids = {device.id for device in devices_data}
    devices_dict = {device.id: device for device in devices_data}
    return device_ids, operations_count, devices_dict


def _subtract_not_results(result: set[str], not_results: list[set[str]]) -> set[str]:
    for i, not_set in enumerate(not_results):
        old_count = len(result)
        result = result.difference(not_set)
        logger.info(
            "  Subtracted NOT operation %s: %s - %s = %s devices",
            i,
            old_count,
            len(not_set),
            len(result),
        )
    return result


def _combine_logical_results(
    *,
    operation_type: str,
    condition_results: list[set[str]],
    not_results: list[set[str]],
    intersect: Callable[[list[set[str]]], set[str]],
    union: Callable[[list[set[str]]], set[str]],
) -> set[str]:
    op_type = operation_type.upper()
    if op_type == "AND":
        result = intersect(condition_results)
        logger.info("  AND operation result (before NOT): %s devices", len(result))
        result = _subtract_not_results(result, not_results)
        logger.info("  AND operation final result: %s devices", len(result))
        return result
    if op_type == "OR":
        result = union(condition_results)
        logger.info("  OR operation result (before NOT): %s devices", len(result))
        result = _subtract_not_results(result, not_results)
        logger.info("  OR operation final result: %s devices", len(result))
        return result
    if op_type == "NOT":
        if condition_results:
            result = union(condition_results)
        else:
            result = set()
        logger.info("  NOT operation devices to exclude: %s devices", len(result))
        return result
    logger.warning("Unknown operation type: %s", operation_type)
    return set()


class NautobotSourceEvaluator:
    """Executes logical operations for inventory device filtering."""

    def __init__(self, query_service: NautobotSourceQueryService):
        self.query_service = query_service
        self.field_to_query_map = {
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

    async def _execute_operation_conditions(
        self, conditions: list[LogicalCondition]
    ) -> tuple[list[set[str]], int, dict[str, DeviceInfo]]:
        condition_results: list[set[str]] = []
        operations_count = 0
        all_devices_data: dict[str, DeviceInfo] = {}

        for i, condition in enumerate(conditions):
            logger.info(
                "  Executing condition %s: %s %s '%s'",
                i,
                condition.field,
                condition.operator,
                condition.value,
            )
            devices, op_count, devices_data = await self._execute_condition(condition)
            condition_results.append(devices)
            operations_count += op_count
            all_devices_data.update(devices_data)
            logger.info("  Condition %s result: %s devices", i, len(devices))

        return condition_results, operations_count, all_devices_data

    async def _execute_nested_operations(
        self, nested_operations: list[LogicalOperation]
    ) -> tuple[list[set[str]], list[set[str]], int, dict[str, DeviceInfo]]:
        nested_results: list[set[str]] = []
        not_results: list[set[str]] = []
        operations_count = 0
        all_devices_data: dict[str, DeviceInfo] = {}

        for i, nested_op in enumerate(nested_operations):
            logger.info("  Executing nested operation %s: type=%s", i, nested_op.operation_type)
            nested_result, nested_count, nested_data = await self._execute_operation(nested_op)
            operations_count += nested_count
            all_devices_data.update(nested_data)
            logger.info(
                "  Nested operation %s result: %s devices, type=%s",
                i,
                len(nested_result),
                nested_op.operation_type,
            )

            if nested_op.operation_type.upper() == "NOT":
                not_results.append(nested_result)
                logger.info("  Added to NOT results for subtraction")
            else:
                nested_results.append(nested_result)
                logger.info("  Added to regular results for combination")

        return nested_results, not_results, operations_count, all_devices_data

    async def _execute_operation(
        self, operation: LogicalOperation
    ) -> tuple[set[str], int, dict[str, DeviceInfo]]:
        """
        Execute a single logical operation.

        Args:
            operation: The logical operation to execute

        Returns:
            Tuple of (device_ids_set, operations_count, devices_data)
        """
        logger.info(
            "Executing operation: type=%s, conditions=%s, nested=%s",
            operation.operation_type,
            len(operation.conditions),
            len(operation.nested_operations),
        )

        operations_count = 0
        all_devices_data: dict[str, DeviceInfo] = {}

        condition_results, cond_count, cond_data = await self._execute_operation_conditions(
            operation.conditions
        )
        operations_count += cond_count
        all_devices_data.update(cond_data)

        nested_results, not_results, nested_count, nested_data = (
            await self._execute_nested_operations(operation.nested_operations)
        )
        operations_count += nested_count
        all_devices_data.update(nested_data)
        condition_results.extend(nested_results)

        result = _combine_logical_results(
            operation_type=operation.operation_type,
            condition_results=condition_results,
            not_results=not_results,
            intersect=self._intersect_sets,
            union=self._union_sets,
        )

        logger.info(
            "Operation completed: %s devices, %s total queries",
            len(result),
            operations_count,
        )
        return result, operations_count, all_devices_data

    async def _query_prefix_field(
        self, field: str, value: str, operator: str
    ) -> tuple[set[str], int, dict[str, DeviceInfo]]:
        if field == "ip_prefix":
            devices_data = await self.query_service._query_devices_by_ip_prefix(value, operator)
        else:
            devices_data = await self.query_service._query_devices_by_primary_prefix(
                value, operator
            )
        return _pack_devices(devices_data)

    async def _query_custom_field_condition(
        self, condition: LogicalCondition
    ) -> tuple[set[str], int, dict[str, DeviceInfo]]:
        use_contains, is_negated = _operator_flags(condition.operator)

        devices_data = await self.query_service._query_devices_by_custom_field(
            condition.field, condition.value, use_contains
        )

        if is_negated:
            devices_data = await self._apply_client_negation(devices_data)

        return _pack_devices(devices_data)

    async def _query_native_not_equals(
        self, field: str, value: str
    ) -> tuple[set[str], int, dict[str, DeviceInfo]] | None:
        handlers: dict[str, Callable[[str], Awaitable[list[DeviceInfo]]]] = {
            "location": lambda v: self.query_service._query_devices_by_location(
                v, use_contains=False, use_negation=True
            ),
            "device_type": lambda v: self.query_service._query_devices_by_devicetype(
                v, use_negation=True
            ),
            "manufacturer": lambda v: self.query_service._query_devices_by_manufacturer(
                v, use_negation=True
            ),
            "role": lambda v: self.query_service._query_devices_by_role(v, use_negation=True),
        }

        handler = handlers.get(field)
        if handler is None:
            return None

        devices_data = await handler(value)
        operations_count = len(devices_data) if field == "location" else 1
        logger.info(
            "Condition %s not_equals '%s' returned %s devices (%s)",
            field,
            value,
            len(devices_data),
            _NATIVE_NOT_EQUALS_LOG_SUFFIX[field],
        )
        return _pack_devices(devices_data, operations_count=operations_count)

    async def _query_mapped_field(
        self, field: str, value: str, use_contains: bool
    ) -> list[DeviceInfo]:
        query_func = self.field_to_query_map[field]

        if field in ["name", "location"] and use_contains:
            return await query_func(value, use_contains=True)
        if field in ["name", "location"]:
            return await query_func(value, use_contains=False)

        if use_contains:
            logger.warning(
                "Field %s does not support 'contains' operator, using exact match",
                field,
            )
        return await query_func(value)

    async def _apply_client_negation(self, matched: list[DeviceInfo]) -> list[DeviceInfo]:
        all_devices = await self.query_service._query_all_devices()
        matched_ids = {device.id for device in matched}
        return [d for d in all_devices if d.id not in matched_ids]

    async def _execute_condition(
        self, condition: LogicalCondition
    ) -> tuple[set[str], int, dict[str, DeviceInfo]]:
        """
        Execute a single condition by calling the appropriate GraphQL query.

        Args:
            condition: The condition to execute

        Returns:
            Tuple of (device_ids_set, operations_count, devices_data)
        """
        try:
            if not condition.field or condition.value is None or condition.value == "":
                logger.warning(
                    "Skipping condition with empty field or value: field=%s, value=%s",
                    condition.field,
                    condition.value,
                )
                return set(), 0, {}

            if condition.field in ("ip_prefix", "primary_prefix"):
                return await self._query_prefix_field(
                    condition.field, condition.value, condition.operator
                )

            if condition.field.startswith("cf_"):
                return await self._query_custom_field_condition(condition)

            query_func = self.field_to_query_map.get(condition.field)
            if not query_func:
                logger.error("No query function found for field: %s", condition.field)
                return set(), 0, {}

            use_contains, is_negated = _operator_flags(condition.operator)

            if condition.operator == "not_equals":
                native_result = await self._query_native_not_equals(
                    condition.field, condition.value
                )
                if native_result is not None:
                    return native_result

            devices_data = await self._query_mapped_field(
                condition.field, condition.value, use_contains
            )

            if is_negated:
                devices_data = await self._apply_client_negation(devices_data)
                logger.info(
                    "Negated condition %s %s '%s' returned %s devices",
                    condition.field,
                    condition.operator,
                    condition.value,
                    len(devices_data),
                )

            logger.info(
                "Condition %s %s '%s' returned %s devices",
                condition.field,
                condition.operator,
                condition.value,
                len(devices_data),
            )

            return _pack_devices(devices_data)

        except Exception as e:
            logger.error(
                "Error executing condition %s=%s: %s",
                condition.field,
                condition.value,
                e,
            )
            return set(), 0, {}

    def _intersect_sets(self, sets: list[set[str]]) -> set[str]:
        """Compute intersection of multiple sets (AND operation)."""
        if not sets:
            return set()
        result = sets[0]
        for s in sets[1:]:
            result = result.intersection(s)
        return result

    def _union_sets(self, sets: list[set[str]]) -> set[str]:
        """Compute union of multiple sets (OR operation)."""
        result = set()
        for s in sets:
            result = result.union(s)
        return result

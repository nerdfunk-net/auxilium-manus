"""
Inventory evaluator — logical operation execution for device filtering.

Extracted from InventoryService as part of Phase 4 decomposition.
See: doc/refactoring/REFACTORING_SERVICES.md — Phase 4
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from models.sources_nautobot import DeviceInfo, LogicalCondition, LogicalOperation

if TYPE_CHECKING:
    from services.sources.nautobot.query_service import NautobotSourceQueryService

logger = logging.getLogger(__name__)


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

        # Execute all conditions in this operation
        condition_results: list[set[str]] = []
        not_results: list[set[str]] = []  # Separate list for NOT operations

        for i, condition in enumerate(operation.conditions):
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

        # Execute nested operations
        for i, nested_op in enumerate(operation.nested_operations):
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

            # Separate NOT operations from regular operations
            if nested_op.operation_type.upper() == "NOT":
                not_results.append(nested_result)
                logger.info("  Added to NOT results for subtraction")
            else:
                condition_results.append(nested_result)
                logger.info("  Added to regular results for combination")

        # Combine results based on operation type
        if operation.operation_type.upper() == "AND":
            result = self._intersect_sets(condition_results)
            logger.info("  AND operation result (before NOT): %s devices", len(result))

            # Subtract all NOT results
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

            logger.info("  AND operation final result: %s devices", len(result))
        elif operation.operation_type.upper() == "OR":
            result = self._union_sets(condition_results)
            logger.info("  OR operation result (before NOT): %s devices", len(result))

            # Subtract all NOT results
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

            logger.info("  OR operation final result: %s devices", len(result))
        elif operation.operation_type.upper() == "NOT":
            # For NOT operations, return the devices that match the conditions
            # The actual NOT logic will be applied in the main preview_inventory method
            if condition_results:
                result = self._union_sets(
                    condition_results
                )  # Get all devices that match the NOT conditions
            else:
                result = set()
            logger.info("  NOT operation devices to exclude: %s devices", len(result))
        else:
            logger.warning("Unknown operation type: %s", operation.operation_type)
            result = set()

        logger.info(
            "Operation completed: %s devices, %s total queries",
            len(result),
            operations_count,
        )
        return result, operations_count, all_devices_data

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
            # Validate condition values - prevent None/empty values from causing issues
            if not condition.field or condition.value is None or condition.value == "":
                logger.warning(
                    "Skipping condition with empty field or value: field=%s, value=%s",
                    condition.field,
                    condition.value,
                )
                return set(), 0, {}

            # Handle ip_prefix — operator is the GraphQL filter type (within_include/within/exact)
            if condition.field == "ip_prefix":
                devices_data = await self.query_service._query_devices_by_ip_prefix(
                    condition.value, condition.operator
                )
                device_ids = {device.id for device in devices_data}
                devices_dict = {device.id: device for device in devices_data}
                return device_ids, 1, devices_dict

            # Check if this is a custom field (starts with cf_)
            if condition.field.startswith("cf_"):
                # Keep the full field name with cf_ prefix for GraphQL query
                use_contains = condition.operator in ["contains", "not_contains"]
                is_negated = condition.operator in ["not_equals", "not_contains"]

                devices_data = await self.query_service._query_devices_by_custom_field(
                    condition.field, condition.value, use_contains
                )

                # Handle negation for custom fields
                if is_negated:
                    all_devices = await self.query_service._query_all_devices()
                    matched_ids = {device.id for device in devices_data}
                    devices_data = [d for d in all_devices if d.id not in matched_ids]

                device_ids = {device.id for device in devices_data}
                devices_dict = {device.id: device for device in devices_data}
                return device_ids, 1, devices_dict

            # Handle regular fields
            query_func = self.field_to_query_map.get(condition.field)
            if not query_func:
                logger.error("No query function found for field: %s", condition.field)
                return set(), 0, {}

            # Determine operator type
            use_contains = condition.operator in ["contains", "not_contains"]
            is_negated = condition.operator in ["not_equals", "not_contains"]

            # Special handling for location with not_equals - use GraphQL location__n filter
            if condition.field == "location" and condition.operator == "not_equals":
                devices_data = await self.query_service._query_devices_by_location(
                    condition.value, use_contains=False, use_negation=True
                )
                device_ids = {device.id for device in devices_data}
                devices_dict = {device.id: device for device in devices_data}
                logger.info(
                    "Condition %s %s '%s' returned %s devices (using GraphQL location__n)",
                    condition.field,
                    condition.operator,
                    condition.value,
                    len(devices_data),
                )
                return device_ids, len(devices_data), devices_dict

            # Special handling for device_type with not_equals - use GraphQL device_type__n filter
            if condition.field == "device_type" and condition.operator == "not_equals":
                devices_data = await self.query_service._query_devices_by_devicetype(
                    condition.value, use_negation=True
                )
                device_ids = {device.id for device in devices_data}
                devices_dict = {device.id: device for device in devices_data}
                logger.info(
                    "Condition %s %s '%s' returned %s devices (using GraphQL device_type__n)",
                    condition.field,
                    condition.operator,
                    condition.value,
                    len(devices_data),
                )
                return device_ids, 1, devices_dict

            # Special handling for manufacturer with not_equals - use GraphQL manufacturer__n filter
            if condition.field == "manufacturer" and condition.operator == "not_equals":
                devices_data = await self.query_service._query_devices_by_manufacturer(
                    condition.value, use_negation=True
                )
                device_ids = {device.id for device in devices_data}
                devices_dict = {device.id: device for device in devices_data}
                logger.info(
                    "Condition %s %s '%s' returned %s devices (using GraphQL manufacturer__n)",
                    condition.field,
                    condition.operator,
                    condition.value,
                    len(devices_data),
                )
                return device_ids, 1, devices_dict

            # Special handling for role with not_equals - use GraphQL role__n filter
            if condition.field == "role" and condition.operator == "not_equals":
                devices_data = await self.query_service._query_devices_by_role(
                    condition.value, use_negation=True
                )
                device_ids = {device.id for device in devices_data}
                devices_dict = {device.id: device for device in devices_data}
                logger.info(
                    "Condition %s %s '%s' returned %s devices (using GraphQL role__n)",
                    condition.field,
                    condition.operator,
                    condition.value,
                    len(devices_data),
                )
                return device_ids, 1, devices_dict

            # Only name and location support contains matching
            if condition.field in ["name", "location"] and use_contains:
                devices_data = await query_func(condition.value, use_contains=True)
            elif condition.field in ["name", "location"]:
                devices_data = await query_func(condition.value, use_contains=False)
            else:
                # Other fields only support exact matching
                if use_contains:
                    logger.warning(
                        "Field %s does not support 'contains' operator, using exact match",
                        condition.field,
                    )
                devices_data = await query_func(condition.value)

            # Handle negation (not_equals, not_contains)
            if is_negated:
                # Get all devices
                all_devices = await self.query_service._query_all_devices()

                # Filter out devices that match the condition
                matched_ids = {device.id for device in devices_data}
                devices_data = [d for d in all_devices if d.id not in matched_ids]

                logger.info(
                    "Negated condition %s %s '%s' returned %s devices",
                    condition.field,
                    condition.operator,
                    condition.value,
                    len(devices_data),
                )

            device_ids = {device.id for device in devices_data}
            devices_dict = {device.id: device for device in devices_data}

            logger.info(
                "Condition %s %s '%s' returned %s devices",
                condition.field,
                condition.operator,
                condition.value,
                len(devices_data),
            )

            return device_ids, 1, devices_dict

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

"""
Shared utility for converting tree-based inventory structure to LogicalOperations.

This module provides a common codebase for evaluating logical expressions from the
tree structure (version 2) used in saved inventories. It mirrors the frontend's
buildOperationsFromTree() logic to ensure consistent evaluation.

Used by:
- API endpoints (when receiving tree from frontend)
- Celery tasks (when loading inventory from database)
- Any service that needs to evaluate saved inventory conditions
"""

import logging
from typing import Any, Dict, List

from models.sources_nautobot import LogicalCondition, LogicalOperation

logger = logging.getLogger(__name__)


def tree_to_operations(tree_data: Dict[str, Any]) -> List[LogicalOperation]:
    """
    Convert tree structure (version 2) to LogicalOperation objects.

    This function mirrors the frontend's buildOperationsFromTree() logic.

    Args:
        tree_data: Tree structure with type, internalLogic, and items

    Returns:
        List of LogicalOperation objects ready for preview_inventory()

    Example tree structure:
        {
            "type": "root",
            "internalLogic": "AND",
            "items": [
                {
                    "id": "xyz",
                    "field": "location",
                    "operator": "equals",
                    "value": "NYC"
                },
                {
                    "id": "abc",
                    "type": "group",
                    "logic": "AND",
                    "internalLogic": "OR",
                    "items": [...]
                }
            ]
        }
    """
    if not tree_data or not isinstance(tree_data, dict):
        logger.warning("Invalid tree data provided")
        return []

    items = tree_data.get("items", [])
    if not items:
        logger.info("Tree has no items")
        return []

    internal_logic = tree_data.get("internalLogic", "AND")

    logger.info(
        "Converting tree with %s items, internal logic: %s", len(items), internal_logic
    )

    # Convert all items
    regular_items = []
    not_items = []

    for item in items:
        converted = _convert_item(item)

        # Check if this is a NOT group
        if (
            isinstance(item, dict)
            and item.get("type") == "group"
            and item.get("logic") == "NOT"
        ):
            # Mark as NOT operation
            converted.operation_type = "NOT"
            not_items.append(converted)
        else:
            regular_items.append(converted)

    operations = []

    # Add main operation with all regular items
    if regular_items:
        if len(regular_items) == 1:
            operations.append(regular_items[0])
        else:
            # Separate root-level conditions from groups
            root_conditions = []
            nested_ops = []

            for item in regular_items:
                # Check if this item represents a group or a single condition
                if len(item.conditions) > 1 or len(item.nested_operations) > 0:
                    # This is a group - add it as a nested operation
                    nested_ops.append(item)
                elif len(item.conditions) == 1:
                    # This is a single condition - add to root conditions
                    root_conditions.extend(item.conditions)

            operations.append(
                LogicalOperation(
                    operation_type=internal_logic,
                    conditions=root_conditions,
                    nested_operations=nested_ops,
                )
            )

    # Add NOT operations
    operations.extend(not_items)

    logger.info("Converted tree to %s operations", len(operations))
    return operations


def _convert_item(item: Dict[str, Any]) -> LogicalOperation:
    """
    Convert a single item (condition or group) to LogicalOperation.

    Args:
        item: Either a ConditionItem or ConditionGroup dict

    Returns:
        LogicalOperation object
    """
    if item.get("type") == "group":
        # This is a group - recursively convert it
        group_conditions = []
        nested_ops = []

        for sub_item in item.get("items", []):
            if sub_item.get("type") == "group":
                # Nested group - recursively convert it
                converted_sub_group = _convert_item(sub_item)

                # Preserve the logic operator (AND/OR/NOT) from the group
                if sub_item.get("logic") == "NOT":
                    converted_sub_group.operation_type = "NOT"

                nested_ops.append(converted_sub_group)
            else:
                # Regular condition
                group_conditions.append(
                    LogicalCondition(
                        field=sub_item.get("field"),
                        operator=sub_item.get("operator"),
                        value=sub_item.get("value"),
                    )
                )

        return LogicalOperation(
            operation_type=item.get("internalLogic", "AND"),
            conditions=group_conditions,
            nested_operations=nested_ops,
        )
    else:
        # This is a simple condition
        return LogicalOperation(
            operation_type="AND",
            conditions=[
                LogicalCondition(
                    field=item.get("field"),
                    operator=item.get("operator"),
                    value=item.get("value"),
                )
            ],
            nested_operations=[],
        )


def convert_saved_inventory_to_operations(
    conditions: List[Any],
) -> List[LogicalOperation]:
    """
    Convert saved inventory conditions to LogicalOperation objects.

    Handles the version 2 tree structure format used by the modern frontend.
    This is the main entry point for celery tasks and other services.

    Args:
        conditions: List containing tree structure (version 2 format)
                   Format: [{"version": 2, "tree": {...}}]

    Returns:
        List of LogicalOperation objects

    Raises:
        ValueError: If conditions format is invalid or unsupported
    """
    if not conditions:
        logger.warning("Empty conditions provided")
        return []

    if not isinstance(conditions, list):
        raise ValueError("Conditions must be a list")

    if len(conditions) == 0:
        logger.warning("Empty conditions list")
        return []

    # Expect version 2 format: [{"version": 2, "tree": {...}}]
    first_item = conditions[0]

    if not isinstance(first_item, dict):
        raise ValueError("Invalid conditions format: expected dict")

    version = first_item.get("version")
    tree = first_item.get("tree")

    if version != 2:
        raise ValueError(
            f"Unsupported conditions format version: {version}. Only version 2 (tree structure) is supported."
        )

    if not tree:
        raise ValueError("Missing tree structure in version 2 format")

    logger.info("Converting version 2 tree structure to operations")
    return tree_to_operations(tree)

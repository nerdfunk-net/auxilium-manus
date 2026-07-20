"""Executor for the list-contains step."""

from __future__ import annotations

import logging
from typing import Any

from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from workflow_steps.common.attribute_path import (
    AttributeState,
    resolve_device_attribute_state,
    resolve_device_value,
)
from workflow_steps.common.update_field_expression import resolve_update_field_expression
from workflow_steps.list_contains.config import get_config

logger = logging.getLogger(__name__)

_OUTCOME_NAMES = ("match", "mismatch", "failure")


def _default_config() -> dict[str, Any]:
    return get_config()


def _parse_bool(config: dict[str, Any], key: str, *, default: bool = False) -> bool:
    value = config.get(key, _default_config().get(key, default))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _item_candidate(item: Any, *, field: str | None) -> Any:
    """Extract the value to compare from one list item: the item itself when
    no field is set (a list of plain scalars), or a dotted lookup into the
    item when it's a dict (a list of objects, e.g. parsed AAA servers)."""
    if not field:
        return item
    current = item
    for part in field.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _find_match(
    items: list[Any],
    *,
    field: str | None,
    target: str,
    case_sensitive: bool,
) -> Any | None:
    normalized_target = target if case_sensitive else target.casefold()
    for item in items:
        candidate = _item_candidate(item, field=field)
        if candidate is None or isinstance(candidate, (dict, list)):
            continue
        text = str(candidate)
        normalized_candidate = text if case_sensitive else text.casefold()
        if normalized_candidate == normalized_target:
            return item
    return None


def _device_failure(
    device: DeviceContext, *, node_id: str, code: str, message: str
) -> DeviceContext:
    err = DeviceError(node_id=node_id, step_id="list-contains", code=code, message=message)
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    del run, artifact_service

    if not context.devices:
        return [StepOutcome(name=name, context=context) for name in _OUTCOME_NAMES]

    list_path = str(config.get("list_path") or "").strip()
    if not list_path:
        raise ValueError("list-contains: list_path is required")

    field = str(config.get("field") or "").strip() or None
    value_expr = str(config.get("value") or "").strip()
    if not value_expr:
        raise ValueError("list-contains: value is required")

    case_sensitive = _parse_bool(config, "case_sensitive", default=False)

    logger.info(
        "list-contains started run_id=%s node_id=%s list_path=%s field=%s",
        context.run_id,
        node_id,
        list_path,
        field,
    )

    buckets: dict[str, dict[str, DeviceContext]] = {"match": {}, "mismatch": {}, "failure": {}}

    for device_id, device in context.devices.items():
        resolved_value = resolve_update_field_expression(
            device=device,
            field_key="value",
            raw_value=value_expr,
            run_id=context.run_id,
        )
        if resolved_value is None:
            buckets["failure"][device_id] = _device_failure(
                device,
                node_id=node_id,
                code="value_unresolved",
                message=f"value expression {value_expr!r} resolved to nothing for this device",
            )
            continue

        state, _ = resolve_device_attribute_state(device, list_path)
        if state in (AttributeState.ABSENT, AttributeState.NULL):
            buckets["failure"][device_id] = _device_failure(
                device,
                node_id=node_id,
                code="list_not_populated",
                message=(
                    f"list_path {list_path!r} is not populated on this device — "
                    "add an upstream step that produces it"
                ),
            )
            continue

        raw_list = resolve_device_value(device, list_path, run_id=context.run_id)
        if not isinstance(raw_list, list):
            got = "nothing" if raw_list is None else type(raw_list).__name__
            buckets["failure"][device_id] = _device_failure(
                device,
                node_id=node_id,
                code="not_a_list",
                message=f"list_path {list_path!r} did not resolve to a list (got {got})",
            )
            continue

        matched_item = _find_match(
            raw_list, field=field, target=resolved_value, case_sensitive=case_sensitive
        )
        matched = matched_item is not None

        parsed = dict(device.parsed)
        parsed[f"{node_id}.membership"] = {
            "kind": "membership_result",
            "matched": matched,
            "list_path": list_path,
            "field": field,
            "value": resolved_value,
            "matched_item": matched_item,
        }
        enriched = device.model_copy(
            update={
                "parsed": parsed,
                "capabilities": device.capabilities | {Capability.PARSED},
                "status": DeviceStatus.OK,
            }
        )
        buckets["match" if matched else "mismatch"][device_id] = enriched

    counts = {name: len(buckets[name]) for name in _OUTCOME_NAMES}
    metadata = {**context.metadata, f"{node_id}.membership_counts": counts}

    logger.info(
        "list-contains finished run_id=%s counts=%s",
        context.run_id,
        counts,
    )

    return [
        StepOutcome(
            name=name,
            context=context.model_copy(
                update={"devices": dict(buckets[name]), "metadata": metadata}
            ),
        )
        for name in _OUTCOME_NAMES
    ]

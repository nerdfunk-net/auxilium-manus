"""Executor for the route-on-attribute control-flow step."""

from __future__ import annotations

import logging
from typing import Any

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.attribute_path import resolve_device_attribute
from workflow_steps.route_on_attribute.config import get_config

logger = logging.getLogger(__name__)


def _default_config() -> dict[str, Any]:
    return get_config()


def _normalize_value(value: str, *, case_sensitive: bool) -> str:
    return value if case_sensitive else value.casefold()


def _parse_routes(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_routes = config.get("routes")
    if raw_routes is None:
        raw_routes = _default_config()["routes"]
    if not isinstance(raw_routes, list) or not raw_routes:
        raise ValueError("route-on-attribute: at least one route is required")

    routes: list[dict[str, Any]] = []
    seen_outcomes: set[str] = set()
    for index, raw_route in enumerate(raw_routes):
        if not isinstance(raw_route, dict):
            raise ValueError(f"route-on-attribute: routes[{index}] must be an object")

        outcome = str(raw_route.get("outcome") or "").strip()
        if not outcome:
            raise ValueError(f"route-on-attribute: routes[{index}].outcome is required")
        if outcome in seen_outcomes:
            raise ValueError(f"route-on-attribute: duplicate outcome {outcome!r}")
        seen_outcomes.add(outcome)

        raw_values = raw_route.get("values")
        if raw_values is None:
            values: list[str] = []
        elif isinstance(raw_values, str):
            values = [item.strip() for item in raw_values.split(",") if item.strip()]
        elif isinstance(raw_values, list):
            values = [str(item).strip() for item in raw_values if str(item).strip()]
        else:
            raise ValueError(f"route-on-attribute: routes[{index}].values must be a list")

        routes.append({"outcome": outcome, "values": values})

    return routes


def _parse_case_sensitive(config: dict[str, Any]) -> bool:
    value = config.get("case_sensitive", _default_config()["case_sensitive"])
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _match_route(
    *,
    device_value: str,
    route_values: list[str],
    case_sensitive: bool,
) -> bool:
    if not route_values:
        return False
    normalized_device_value = _normalize_value(device_value, case_sensitive=case_sensitive)
    normalized_route_values = {
        _normalize_value(value, case_sensitive=case_sensitive) for value in route_values
    }
    return normalized_device_value in normalized_route_values


def _route_devices(
    *,
    devices: dict[str, DeviceContext],
    attribute_path: str,
    routes: list[dict[str, Any]],
    default_outcome: str | None,
    case_sensitive: bool,
) -> tuple[dict[str, dict[str, DeviceContext]], list[str], list[str]]:
    buckets: dict[str, dict[str, DeviceContext]] = {
        route["outcome"]: {} for route in routes
    }
    if default_outcome:
        buckets.setdefault(default_outcome, {})

    unmatched_device_ids: list[str] = []
    missing_attribute_device_ids: list[str] = []

    for device_id, device in devices.items():
        resolved = resolve_device_attribute(device, attribute_path)
        if resolved is None:
            missing_attribute_device_ids.append(device_id)
            if default_outcome:
                buckets[default_outcome][device_id] = device
            else:
                unmatched_device_ids.append(device_id)
            continue

        matched_outcome: str | None = None
        for route in routes:
            if _match_route(
                device_value=resolved,
                route_values=route["values"],
                case_sensitive=case_sensitive,
            ):
                matched_outcome = route["outcome"]
                break

        if matched_outcome is not None:
            buckets[matched_outcome][device_id] = device
            continue

        if default_outcome:
            buckets[default_outcome][device_id] = device
        else:
            unmatched_device_ids.append(device_id)

    return buckets, unmatched_device_ids, missing_attribute_device_ids


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
        return [StepOutcome(name="success", context=context)]

    attribute_path = str(
        config.get("attribute_path") or _default_config()["attribute_path"]
    ).strip()
    if not attribute_path:
        raise ValueError("route-on-attribute: attribute_path is required")

    routes = _parse_routes(config)
    case_sensitive = _parse_case_sensitive(config)
    default_outcome = str(config.get("default_outcome") or "").strip() or None

    buckets, unmatched_device_ids, missing_attribute_device_ids = _route_devices(
        devices=context.devices,
        attribute_path=attribute_path,
        routes=routes,
        default_outcome=default_outcome,
        case_sensitive=case_sensitive,
    )

    if unmatched_device_ids:
        sample = ", ".join(unmatched_device_ids[:5])
        suffix = "..." if len(unmatched_device_ids) > 5 else ""
        raise ValueError(
            "route-on-attribute: "
            f"{len(unmatched_device_ids)} device(s) matched no route and no default_outcome "
            f"was configured ({sample}{suffix})"
        )

    outcome_names = [route["outcome"] for route in routes]
    if default_outcome and default_outcome not in outcome_names:
        outcome_names.append(default_outcome)

    routed_counts = {
        outcome_name: len(buckets.get(outcome_name, {})) for outcome_name in outcome_names
    }
    metadata = {
        **context.metadata,
        f"{node_id}.attribute_path": attribute_path,
        f"{node_id}.routed_counts": routed_counts,
        f"{node_id}.missing_attribute_device_ids": missing_attribute_device_ids,
    }

    logger.info(
        "route-on-attribute node_id=%s attribute_path=%s routed_counts=%s",
        node_id,
        attribute_path,
        routed_counts,
    )

    return [
        StepOutcome(
            name=outcome_name,
            context=context.model_copy(
                update={
                    "devices": dict(buckets.get(outcome_name, {})),
                    "metadata": metadata,
                }
            ),
        )
        for outcome_name in outcome_names
    ]

"""Executor for the get-from-list step."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from core.models.runs import WorkflowRun
from models.workflow_context import Capability, DeviceContext, DeviceStatus, StepOutcome, WorkflowContext, bare_hostname
from services.artifacts import ArtifactService

logger = logging.getLogger(__name__)


def _normalize_device_names(raw_devices: Any) -> list[str]:
    if not isinstance(raw_devices, list):
        return []

    names: list[str] = []
    seen: set[str] = set()
    for item in raw_devices:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            raw_name = item.get("name")
            name = str(raw_name).strip() if raw_name is not None else ""
        else:
            continue

        if not name:
            continue

        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)

    return names


def _device_context_from_name(name: str, *, index: int, node_id: str) -> DeviceContext:
    digest = hashlib.sha256(f"{node_id}:{name}:{index}".encode()).hexdigest()[:32]
    device_id = f"list-{digest}"

    return DeviceContext(
        id=device_id,
        name=name,
        hostname=bare_hostname(None, name),
        source="list",
        source_id=node_id,
        attribute_bags={"list": {"name": name, "index": index}},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    del artifact_service  # unused for this step

    logger.info("get-from-list started run_id=%s", run.id)

    device_names = _normalize_device_names(config.get("devices"))
    if not device_names:
        raise ValueError("get-from-list: at least one device name is required")

    new_devices = {
        device.id: device
        for index, name in enumerate(device_names)
        for device in [_device_context_from_name(name, index=index, node_id=node_id)]
    }

    fan_out_cfg: dict = config.get("fan_out") or {}
    fan_out_enabled = bool(fan_out_cfg.get("enabled", False))

    metadata_update: dict = {
        **context.metadata,
        f"{node_id}.total": len(new_devices),
        f"{node_id}.devices": device_names,
    }
    if fan_out_enabled:
        metadata_update["_fan_out"] = {
            "enabled": True,
            "mode": fan_out_cfg.get("mode", "per_device"),
            "chunk_size": max(1, int(fan_out_cfg.get("chunk_size", 1))),
            "max_concurrency": max(0, int(fan_out_cfg.get("max_concurrency", 0))),
            "inventory_node_id": node_id,
        }

    logger.info(
        "get-from-list returning %d devices run_id=%s",
        len(new_devices),
        run.id,
    )

    new_context = context.model_copy(
        update={
            "devices": {**context.devices, **new_devices},
            "metadata": metadata_update,
        }
    )
    return [StepOutcome(name="success", context=new_context)]

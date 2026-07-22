"""Executor for the get-from-list step."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, NamedTuple

from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
    bare_hostname,
)
from services.artifacts import ArtifactService
from services.nautobot.common.validators import validate_ip_address
from workflow_steps.common.fan_out import build_fan_out_metadata

logger = logging.getLogger(__name__)


class _DeviceEntry(NamedTuple):
    name: str | None
    ip_address: str | None


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_device_entries(raw_devices: Any) -> list[_DeviceEntry]:
    if not isinstance(raw_devices, list):
        return []

    entries: list[_DeviceEntry] = []
    seen: set[tuple[str | None, str | None]] = set()
    for index, item in enumerate(raw_devices):
        if isinstance(item, str):
            name = _clean_str(item)
            ip_address = None
        elif isinstance(item, dict):
            name = _clean_str(item.get("name"))
            ip_address = _clean_str(item.get("ip_address"))
        else:
            continue

        if name is None and ip_address is None:
            continue

        if ip_address is not None and not validate_ip_address(ip_address):
            raise ValueError(
                f"get-from-list: invalid IP address '{ip_address}' (row {index + 1})"
            )

        key = (name.casefold() if name else None, ip_address)
        if key in seen:
            continue
        seen.add(key)
        entries.append(_DeviceEntry(name=name, ip_address=ip_address))

    return entries


def _device_context_from_entry(entry: _DeviceEntry, *, index: int, node_id: str) -> DeviceContext:
    display_name = entry.name or entry.ip_address
    assert display_name is not None  # enforced by _normalize_device_entries

    digest = hashlib.sha256(
        f"{node_id}:{entry.name or ''}:{entry.ip_address or ''}:{index}".encode()
    ).hexdigest()[:32]
    device_id = f"list-{digest}"

    return DeviceContext(
        id=device_id,
        name=display_name,
        hostname=bare_hostname(entry.ip_address, display_name),
        primary_ip4=entry.ip_address,
        source="list",
        source_id=node_id,
        attribute_bags={
            "list": {"name": entry.name, "ip_address": entry.ip_address, "index": index}
        },
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

    device_entries = _normalize_device_entries(config.get("devices"))
    if not device_entries:
        raise ValueError("get-from-list: at least one device name or IP address is required")

    new_devices = {
        device.id: device
        for index, entry in enumerate(device_entries)
        for device in [_device_context_from_entry(entry, index=index, node_id=node_id)]
    }

    fan_out_metadata = build_fan_out_metadata(config.get("fan_out"), node_id)

    metadata_update: dict = {
        **context.metadata,
        f"{node_id}.total": len(new_devices),
        f"{node_id}.devices": [device.name for device in new_devices.values()],
    }
    if fan_out_metadata is not None:
        metadata_update["_fan_out"] = fan_out_metadata

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

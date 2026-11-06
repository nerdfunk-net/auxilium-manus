"""Shared target handling for steps that read facts of Cisco ACI switches.

An ACI step only works on devices that came from an ACI source (``get-aci-devices``): their
``attribute_bags["aci"]`` carries the node and pod id the APIC addresses a switch by. Devices are
grouped by ``source_id`` so one step can span several fabrics; credentials resolve once per source,
before any I/O.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

import service_factory
from models.workflow_context import DeviceContext
from services.aci.common.exceptions import AciValidationError
from services.aci.credentials import AciCredentials
from services.aci.source_config_service import AciSourceNotFoundError
from workflow_steps.common.device_outcomes import TargetSplit, failed_device

ACI_SOURCE = "aci"


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def node_of(device: DeviceContext) -> tuple[int, int] | None:
    """``(pod_id, node_id)`` of an ACI device, or ``None`` when its bag does not carry both."""
    bag = device.attribute_bags.get(ACI_SOURCE)
    if not isinstance(bag, dict):
        return None
    pod_id, node_id = _positive_int(bag.get("pod_id")), _positive_int(bag.get("node_id"))
    if pod_id is None or node_id is None:
        return None
    return pod_id, node_id


def split_targets(devices: dict[str, DeviceContext], *, step_id: str, node_id: str) -> TargetSplit:
    """Group ACI switches by source; reject devices from any other source or without a node."""
    by_source: dict[str, dict[str, DeviceContext]] = {}
    rejected: dict[str, DeviceContext] = {}
    for device_id, device in devices.items():
        if device.source != ACI_SOURCE or not device.source_id:
            rejected[device_id] = failed_device(
                device,
                step_id=step_id,
                node_id=node_id,
                code="not_aci_device",
                message=(
                    f"Device {device_id} did not come from a Cisco ACI source "
                    f"(source={device.source or 'unknown'})"
                ),
            )
        elif node_of(device) is None:
            rejected[device_id] = failed_device(
                device,
                step_id=step_id,
                node_id=node_id,
                code="aci_node_unknown",
                message=(
                    f"Device {device_id} carries no ACI node and pod id; use Get from ACI first"
                ),
            )
        else:
            by_source.setdefault(device.source_id, {})[device_id] = device
    return TargetSplit(by_source=by_source, rejected=rejected)


def resolve_source_credentials(
    db: Session, source_ids: list[str], *, step_id: str
) -> dict[str, AciCredentials]:
    """Resolve credentials per source; a bad source is a configuration error (ValueError)."""
    source_config = service_factory.build_aci_source_config_service(db)
    resolved: dict[str, AciCredentials] = {}
    for source_id in source_ids:
        try:
            resolved[source_id] = source_config.resolve_credentials(source_id)
        except AciSourceNotFoundError as exc:
            raise ValueError(f"{step_id}: Cisco ACI source '{source_id}' not found") from exc
        except AciValidationError as exc:
            raise ValueError(f"{step_id}: {exc}") from exc
    return resolved

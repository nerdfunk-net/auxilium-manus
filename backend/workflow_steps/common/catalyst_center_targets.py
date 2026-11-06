"""Shared target handling for steps that act on devices through Cisco Catalyst Center.

A Catalyst Center step only works on devices that came from a Catalyst Center source (their
``id`` is the controller's device UUID). Devices are grouped by ``source_id`` so one step can
span several controllers; credentials resolve once per source, before any I/O.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

import service_factory
from models.workflow_context import DeviceContext
from services.catalyst_center.common.exceptions import CatalystCenterValidationError
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.catalyst_center.source_config_service import CatalystCenterSourceNotFoundError
from workflow_steps.common.device_outcomes import (
    TargetSplit,
    build_outcomes,
    failed_device,
)

CATALYST_CENTER_SOURCE = "catalyst_center"

# ``TargetSplit``, ``build_outcomes`` and ``failed_device`` live in ``device_outcomes`` (shared with
# the ACI steps) and stay importable from here.
__all__ = [
    "CATALYST_CENTER_SOURCE",
    "TargetSplit",
    "build_outcomes",
    "failed_device",
    "resolve_source_credentials",
    "split_targets",
]


def split_targets(devices: dict[str, DeviceContext], *, step_id: str, node_id: str) -> TargetSplit:
    """Group Catalyst Center devices by source; reject devices from any other source."""
    by_source: dict[str, dict[str, DeviceContext]] = {}
    rejected: dict[str, DeviceContext] = {}
    for device_id, device in devices.items():
        if device.source != CATALYST_CENTER_SOURCE or not device.source_id:
            rejected[device_id] = failed_device(
                device,
                step_id=step_id,
                node_id=node_id,
                code="not_catalyst_center_device",
                message=(
                    f"Device {device_id} did not come from a Catalyst Center source "
                    f"(source={device.source or 'unknown'})"
                ),
            )
            continue
        by_source.setdefault(device.source_id, {})[device_id] = device
    return TargetSplit(by_source=by_source, rejected=rejected)


def resolve_source_credentials(
    db: Session, source_ids: list[str], *, step_id: str
) -> dict[str, CatalystCenterCredentials]:
    """Resolve credentials per source; a bad source is a configuration error (ValueError)."""
    source_config = service_factory.build_catalyst_center_source_config_service(db)
    resolved: dict[str, CatalystCenterCredentials] = {}
    for source_id in source_ids:
        try:
            resolved[source_id] = source_config.resolve_credentials(source_id)
        except CatalystCenterSourceNotFoundError as exc:
            raise ValueError(f"{step_id}: Catalyst Center source '{source_id}' not found") from exc
        except CatalystCenterValidationError as exc:
            raise ValueError(f"{step_id}: {exc}") from exc
    return resolved

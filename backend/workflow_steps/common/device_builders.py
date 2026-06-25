"""Helpers for constructing DeviceContext entries in step executors."""

from __future__ import annotations

import hashlib
from typing import Any

from models.sources_nautobot import DeviceInfo
from models.workflow_context import Capability, DeviceContext, DeviceStatus, bare_hostname


def device_context_from_nautobot(
    device: DeviceInfo,
    *,
    source_id: str,
) -> DeviceContext:
    platform_detail = None
    network_driver = device.platform_network_driver
    if device.platform or network_driver:
        platform_detail = device.platform

    return DeviceContext(
        id=device.id,
        name=device.name or device.id,
        hostname=bare_hostname(device.primary_ip4, device.name or device.id),
        platform=platform_detail,
        network_driver=network_driver,
        primary_ip4=device.primary_ip4,
        source="nautobot",
        source_id=source_id,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


def device_context_from_git_detail(
    detail: dict[str, Any],
    *,
    source_id: str,
    index: int,
) -> DeviceContext:
    name = str(detail.get("name") or detail.get("hostname") or f"git-device-{index}")
    primary_ip4 = detail.get("primary_ip4")
    if isinstance(primary_ip4, dict):
        primary_ip4 = primary_ip4.get("address")
    if primary_ip4 is not None:
        primary_ip4 = str(primary_ip4)

    platform = detail.get("platform")
    network_driver = None
    platform_name = None
    if isinstance(platform, dict):
        platform_name = platform.get("name")
        network_driver = platform.get("network_driver")
    elif isinstance(platform, str):
        platform_name = platform

    device_id = str(detail.get("id") or "").strip()
    if not device_id:
        digest = hashlib.sha256(f"{source_id}:{name}:{index}".encode()).hexdigest()[:32]
        device_id = f"git-{digest}"

    return DeviceContext(
        id=device_id,
        name=name,
        hostname=bare_hostname(primary_ip4, name),
        platform=platform_name,
        network_driver=network_driver,
        primary_ip4=primary_ip4,
        source="git",
        source_id=source_id,
        attribute_bags={"git": dict(detail)},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )

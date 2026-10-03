"""Helpers for constructing DeviceContext entries in step executors."""

from __future__ import annotations

import hashlib
from typing import Any

from models.catalyst_center import CatalystCenterDevice
from models.sources_nautobot import DeviceInfo
from models.workflow_context import Capability, DeviceContext, DeviceStatus, bare_hostname
from services.workflow_context.secret_fields import seal_secret


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


# Catalyst Center ``softwareType`` -> workflow ``network_driver`` (values understood by
# services/network/netmiko/platform.py). Unknown types leave the driver unset so SSH steps
# fall back to their own default / override instead of guessing.
_CATALYST_CENTER_DRIVERS: dict[str, str] = {
    "ios-xe": "cisco_xe",
    "ios-xr": "cisco_xr",
    "nx-os": "cisco_nxos",
    "ios": "cisco_ios",
}


def device_context_from_catalyst_center(
    device: CatalystCenterDevice,
    *,
    source_id: str,
) -> DeviceContext:
    """Build a DeviceContext from a normalized Cisco Catalyst Center device.

    The full raw inventory record is kept (copied) in ``attribute_bags["catalyst_center"]``
    for downstream steps; the controller's device-list payload carries no secrets.
    """
    name = device.hostname or device.management_ip or device.id
    driver = _CATALYST_CENTER_DRIVERS.get((device.software_type or "").strip().lower())

    return DeviceContext(
        id=device.id,
        name=name,
        hostname=bare_hostname(device.management_ip, name),
        platform=device.software_type,
        network_driver=driver,
        primary_ip4=device.management_ip,
        source="catalyst_center",
        source_id=source_id,
        attribute_bags={"catalyst_center": dict(device.raw)},
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


def device_context_from_config_match(
    hostname: str,
    *,
    source_id: str,
    file_path: str,
    commit: str | None,
) -> DeviceContext:
    """Build a DeviceContext for a device found by searching Git config files.

    Only the hostname is known at this point (no IP/platform) — the device was
    discovered by matching text inside a config file, not resolved from an
    inventory API.
    """
    digest = hashlib.sha256(f"{source_id}:{hostname}:{file_path}".encode()).hexdigest()[:32]
    device_id = f"cfg-{digest}"

    git_bag: dict[str, Any] = {"file_path": file_path}
    if commit:
        git_bag["commit"] = commit

    return DeviceContext(
        id=device_id,
        name=hostname,
        hostname=bare_hostname(None, hostname),
        source="git",
        source_id=source_id,
        attribute_bags={"git": git_bag},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


def device_context_from_ise(
    device: dict[str, Any],
    *,
    source_id: str,
) -> DeviceContext:
    """Build a DeviceContext from a raw Cisco ISE NetworkDevice dict.

    An ISE ``NetworkDevice`` entry does not always represent a single host —
    if its ``NetworkDeviceIPList`` entry uses a netmask other than /32, the
    entry may actually represent a subnet or a group of devices rather than
    one device. The raw entry (including that ambiguity) is preserved as-is
    in ``attribute_bags["ise"]`` so downstream steps/users can inspect it;
    resolving such entries into individual devices is handled by the caller.
    """
    name = str(device.get("name") or device.get("id") or "unknown")

    ip_list = device.get("NetworkDeviceIPList") or []
    primary_ip4: str | None = None
    mask: int | None = None
    if ip_list:
        first_ip = ip_list[0]
        primary_ip4 = first_ip.get("ipaddress")
        mask = first_ip.get("mask")

    is_group_or_prefix = mask is not None and mask != 32

    device_id = str(device.get("id") or "").strip()
    if not device_id:
        digest = hashlib.sha256(f"{source_id}:{name}".encode()).hexdigest()[:32]
        device_id = f"ise-{digest}"

    ise_bag: dict[str, Any] = {**device, "is_group_or_prefix": is_group_or_prefix}

    # Surfaced as its own top-level Jinja variable (build_jinja_context flattens
    # attribute_bags by name), so a template can use {{ tacacs.shared_secret }}
    # directly instead of drilling into ise.tacacsSettings.sharedSecret. Both
    # copies are sealed — this bag is not a second cleartext channel.
    attribute_bags: dict[str, dict[str, Any]] = {"ise": ise_bag}
    tacacs_settings = device.get("tacacsSettings")
    if isinstance(tacacs_settings, dict):
        shared_secret = tacacs_settings.get("sharedSecret")
        if shared_secret:
            attribute_bags["tacacs"] = {"shared_secret": seal_secret(str(shared_secret))}
            ise_bag["tacacsSettings"] = {
                **tacacs_settings,
                "sharedSecret": seal_secret(str(shared_secret)),
            }

    return DeviceContext(
        id=device_id,
        name=name,
        hostname=bare_hostname(primary_ip4, name),
        primary_ip4=primary_ip4,
        source="ise",
        source_id=source_id,
        attribute_bags=attribute_bags,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )

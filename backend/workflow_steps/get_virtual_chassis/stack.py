"""Pure helpers for the get-virtual-chassis step (no I/O).

A Nautobot virtual chassis (a Cisco stack) is one logical device reachable only via the
master member's primary IPv4. Member device names are unique in Nautobot, so non-master
members carry a marker in the name (``LAB:2.local.zz``); the sequence number extracted from
that marker is what later steps use to address one member of a parsed command output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    bare_hostname,
)
from workflow_steps.common.step_flags import parse_bool_flag
from workflow_steps.common.virtual_chassis import (
    DEFAULT_INDEX_KEY,
    bag_name,
    member_bag,
    plain_name,
)

STEP_ID = "get-virtual-chassis"

NAME_MATCH_MODES = ("exact", "contains", "regex")
MAX_REGEX_LENGTH = 200

DEFAULT_INDEX_REGEX = r":(\d+)"


@dataclass(frozen=True)
class StackSettings:
    """Validated, immutable view of the step's pluginConfig."""

    name_filter: str
    name_match: str
    name_filter_regex: re.Pattern[str] | None
    split_members: bool
    index_regex: re.Pattern[str]
    index_offset: int
    index_default: int
    attribute_bag: str
    index_key: str


def _as_int(config: dict[str, Any], key: str, default: int) -> int:
    raw = config.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default
    if isinstance(raw, bool):
        raise ValueError(f"{STEP_ID}: {key} must be an integer")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{STEP_ID}: {key} must be an integer (got {raw!r})") from exc


def _compile(pattern: str, key: str) -> re.Pattern[str]:
    if not pattern.strip():
        raise ValueError(f"{STEP_ID}: {key} must not be empty")
    if len(pattern) > MAX_REGEX_LENGTH:
        raise ValueError(f"{STEP_ID}: {key} is longer than {MAX_REGEX_LENGTH} characters")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"{STEP_ID}: {key} is not a valid regular expression: {exc}") from exc


def parse_settings(config: dict[str, Any]) -> StackSettings:
    """Validate ``config`` and compile its regexes. Raises ``ValueError`` on bad input."""
    name_match = str(config.get("name_match") or "exact").strip()
    if name_match not in NAME_MATCH_MODES:
        raise ValueError(f"{STEP_ID}: name_match must be one of {', '.join(NAME_MATCH_MODES)}")

    name_filter = str(config.get("name_filter") or "").strip()
    name_filter_regex = (
        _compile(name_filter, "name_filter") if name_match == "regex" and name_filter else None
    )

    return StackSettings(
        name_filter=name_filter,
        name_match=name_match,
        name_filter_regex=name_filter_regex,
        split_members=parse_bool_flag(config, "split_members"),
        index_regex=_compile(str(config.get("index_regex") or DEFAULT_INDEX_REGEX), "index_regex"),
        index_offset=_as_int(config, "index_offset", -1),
        index_default=_as_int(config, "index_default", 0),
        attribute_bag=bag_name(config, step_id=STEP_ID),
        index_key=plain_name(config, "index_key", DEFAULT_INDEX_KEY, step_id=STEP_ID),
    )


def matches_name(name: str, settings: StackSettings) -> bool:
    """Whether a virtual chassis name passes the step's name filter (empty = all)."""
    if not settings.name_filter:
        return True
    if settings.name_match == "contains":
        return settings.name_filter.lower() in name.lower()
    if settings.name_filter_regex is not None:
        return settings.name_filter_regex.search(name) is not None
    return name == settings.name_filter


def member_index(name: str, settings: StackSettings) -> int:
    """Sequence number of a member: captured number + offset, or the default.

    The first capture group is used (the whole match when the pattern has no group). A
    name that does not match, or whose capture is not an integer, gets ``index_default``.
    """
    match = settings.index_regex.search(name)
    if match is None:
        return settings.index_default
    raw = match.group(1) if settings.index_regex.groups else match.group(0)
    try:
        return int(raw) + settings.index_offset
    except TypeError, ValueError:
        return settings.index_default


def _position_key(member: dict[str, Any]) -> tuple[bool, int, str]:
    position = member.get("vc_position")
    return (
        not isinstance(position, int),
        position if isinstance(position, int) else 0,
        str(member.get("name") or ""),
    )


def pick_master(members: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The member flagged ``vc_master_for``; else the one with the lowest position."""
    for member in members:
        if member.get("vc_master_for"):
            return member
    ordered = sorted(members, key=_position_key)
    return ordered[0] if ordered else None


def _address(member: dict[str, Any] | None) -> str | None:
    if member is None:
        return None
    ip = member.get("primary_ip4")
    address = ip.get("address") if isinstance(ip, dict) else None
    return str(address) if address else None


def _device_type_model(member: dict[str, Any]) -> str | None:
    device_type = member.get("device_type")
    model = device_type.get("model") if isinstance(device_type, dict) else None
    return str(model) if model else None


def _platform(member: dict[str, Any] | None) -> tuple[str | None, str | None]:
    platform = member.get("platform") if member else None
    if not isinstance(platform, dict):
        return None, None
    return platform.get("name") or None, platform.get("network_driver") or None


def _member_record(
    member: dict[str, Any], *, settings: StackSettings, master: dict[str, Any] | None
) -> dict[str, Any]:
    name = str(member.get("name") or "")
    return {
        "id": member.get("id"),
        "name": name,
        "position": member.get("vc_position"),
        "priority": member.get("vc_priority"),
        "serial": member.get("serial") or None,
        "device_type": _device_type_model(member),
        "primary_ip4": _address(member),
        "is_master": member is master,
        settings.index_key: member_index(name, settings),
    }


def _failed_device(
    *, device_id: str, name: str, source_id: str, node_id: str, message: str, code: str
) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=name,
        hostname=name,
        source="nautobot",
        source_id=source_id,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.FAILED,
        errors=[DeviceError(node_id=node_id, step_id=STEP_ID, code=code, message=message)],
    )


def build_stack_devices(
    vc: dict[str, Any], settings: StackSettings, *, source_id: str, node_id: str
) -> list[DeviceContext]:
    """Turn one GraphQL ``virtual_chassis`` object into workflow devices.

    Unsplit: a single device for the whole stack (id of the master member, name of the
    chassis). Split: one device per member, all connecting through the master's IP. A
    stack without a master IP yields ``FAILED`` devices so the executor can route them to
    the ``failure`` outcome.
    """
    vc_id = str(vc.get("id") or "")
    vc_name = str(vc.get("name") or vc_id)
    raw_members = vc.get("members")
    members = sorted(
        (m for m in raw_members if isinstance(m, dict)) if isinstance(raw_members, list) else [],
        key=_position_key,
    )
    master = pick_master(members)
    master_ip = _address(master)

    if master is None or master_ip is None:
        reason = "has no members" if master is None else "master member has no primary IPv4"
        message = f"Virtual chassis {vc_name!r} {reason}"
        if settings.split_members and members:
            identities = [(str(m.get("id")), str(m.get("name"))) for m in members]
        else:
            identities = [(str(master.get("id")) if master else vc_id, vc_name)]
        return [
            _failed_device(
                device_id=device_id,
                name=name,
                source_id=source_id,
                node_id=node_id,
                message=message,
                code="no_primary_ip",
            )
            for device_id, name in identities
        ]

    records = [_member_record(m, settings=settings, master=master) for m in members]
    platform_name, network_driver = _platform(master)
    master_name = str(master.get("name") or "")

    if not settings.split_members:
        master_record = next(r for r in records if r["is_master"])
        return [
            DeviceContext(
                id=str(master.get("id")),
                name=vc_name,
                hostname=bare_hostname(master_ip, vc_name),
                platform=platform_name,
                network_driver=network_driver,
                primary_ip4=master_ip,
                source="nautobot",
                source_id=source_id,
                attribute_bags={
                    settings.attribute_bag: {
                        "vc_id": vc_id,
                        "vc_name": vc_name,
                        "member_count": len(records),
                        "master": master_record,
                        "members": records,
                    }
                },
                capabilities={Capability.IDENTITY},
                status=DeviceStatus.OK,
            )
        ]

    devices: list[DeviceContext] = []
    for member, record in zip(members, records, strict=True):
        member_platform, member_driver = _platform(member)
        name = record["name"]
        devices.append(
            DeviceContext(
                id=str(member.get("id")),
                name=name,
                hostname=bare_hostname(master_ip, name),
                platform=member_platform or platform_name,
                network_driver=member_driver or network_driver,
                primary_ip4=master_ip,
                source="nautobot",
                source_id=source_id,
                attribute_bags={
                    settings.attribute_bag: member_bag(
                        vc_id=vc_id,
                        vc_name=vc_name,
                        member_count=len(records),
                        record=record,
                        master_name=master_name,
                    )
                },
                capabilities={Capability.IDENTITY},
                status=DeviceStatus.OK,
            )
        )
    return devices

"""Pure helpers for the get-virtual-chassis step (no I/O).

A Nautobot virtual chassis (a Cisco stack) is one logical device reachable only via the
master member's primary IPv4. Member device names are unique in Nautobot, so non-master
members carry a marker in the name (``LAB:2.local.zz``); the sequence number extracted from
that marker is what later steps use to address one member of a parsed command output.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from nautobot_read.queries.virtual_chassis import (
    address_of,
    member_record,
    ordered_members,
    pick_master,
    platform_of,
)

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    bare_hostname,
)
from workflow_steps.common.failure_records import MISSING_DATA
from workflow_steps.common.regex_search import RegexAnswer, RegexQuestion, search_many
from workflow_steps.common.step_flags import parse_bool_flag
from workflow_steps.common.virtual_chassis import (
    DEFAULT_INDEX_KEY,
    bag_name,
    member_bag,
    plain_name,
)
from workflow_steps.get_virtual_chassis.config import get_config

STEP_ID = "get-virtual-chassis"

NAME_MATCH_MODES = ("exact", "contains", "regex")
MAX_REGEX_LENGTH = 200



@dataclass(frozen=True)
class StackSettings:
    """Validated, immutable view of the step's pluginConfig."""

    name_filter: str
    name_match: str
    name_filter_pattern: str | None
    split_members: bool
    index_pattern: str
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


def _validated_pattern(pattern: str, key: str) -> str:
    """The pattern, once it is known to be a valid regular expression (it is never run here)."""
    if not pattern.strip():
        raise ValueError(f"{STEP_ID}: {key} must not be empty")
    if len(pattern) > MAX_REGEX_LENGTH:
        raise ValueError(f"{STEP_ID}: {key} is longer than {MAX_REGEX_LENGTH} characters")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"{STEP_ID}: {key} is not a valid regular expression: {exc}") from exc
    return pattern


def parse_settings(config: dict[str, Any]) -> StackSettings:
    """Validate ``config`` and compile its regexes. Raises ``ValueError`` on bad input."""
    name_match = str(config.get("name_match") or get_config()["name_match"]).strip()
    if name_match not in NAME_MATCH_MODES:
        raise ValueError(f"{STEP_ID}: name_match must be one of {', '.join(NAME_MATCH_MODES)}")

    name_filter = str(config.get("name_filter") or "").strip()
    name_filter_pattern = (
        _validated_pattern(name_filter, "name_filter")
        if name_match == "regex" and name_filter
        else None
    )

    return StackSettings(
        name_filter=name_filter,
        name_match=name_match,
        name_filter_pattern=name_filter_pattern,
        split_members=parse_bool_flag(config, "split_members"),
        index_pattern=_validated_pattern(
            str(config.get("index_regex") or get_config()["index_regex"]), "index_regex"
        ),
        index_offset=_as_int(config, "index_offset", -1),
        index_default=_as_int(config, "index_default", 0),
        attribute_bag=bag_name(config, step_id=STEP_ID),
        index_key=plain_name(config, "index_key", DEFAULT_INDEX_KEY, step_id=STEP_ID),
    )


Answers = Mapping[str, RegexAnswer]
"""The isolated worker's answer for each text the step's pattern was asked about."""

_STOPPED_MESSAGE = "{step}: {key} was stopped: it used too much time or memory on a name"


async def _ask(pattern: str, texts: Iterable[str], *, key: str) -> Answers:
    names = sorted(set(texts))
    answers = await search_many([RegexQuestion(text=name, pattern=pattern) for name in names])
    if any(a.status in ("stopped", "invalid") for a in answers):
        raise ValueError(_STOPPED_MESSAGE.format(step=STEP_ID, key=key))
    return dict(zip(names, answers, strict=True))


async def answer_name_filter(vcs: Sequence[dict[str, Any]], settings: StackSettings) -> Answers:
    """Ask the worker the name filter for every chassis name (nothing unless mode is regex)."""
    if settings.name_filter_pattern is None:
        return {}
    names = [str(vc.get("name") or "") for vc in vcs]
    return await _ask(settings.name_filter_pattern, names, key="name_filter")


async def answer_member_indexes(vcs: Sequence[dict[str, Any]], settings: StackSettings) -> Answers:
    """Ask the worker the index regex for every member name of the chassis that stay."""
    names = [
        member_record(member, master=None)["name"] for vc in vcs for member in ordered_members(vc)
    ]
    return await _ask(settings.index_pattern, names, key="index_regex")


def matches_name(name: str, settings: StackSettings, answers: Answers) -> bool:
    """Whether a virtual chassis name passes the step's name filter (empty = all).

    ``answers`` holds the worker's answers of ``answer_name_filter`` (used in regex mode only).
    """
    if not settings.name_filter:
        return True
    if settings.name_match == "contains":
        return settings.name_filter.lower() in name.lower()
    if settings.name_filter_pattern is not None:
        return answers[name].found
    # Exact ignores case, like the assistant's get_virtual_chassis: "lab.local.zz" finds the
    # stack Nautobot stores as "LAB.local.zz" (an exact match is no longer sent to Nautobot).
    return name.casefold() == settings.name_filter.casefold()


def member_index(name: str, settings: StackSettings, answers: Answers) -> int:
    """Sequence number of a member: captured number + offset, or the default.

    The first capture group is used (the whole match when the pattern has no group). A
    name that does not match, or whose capture is not an integer, gets ``index_default``.
    ``answers`` holds the worker's answers of ``answer_member_indexes``.
    """
    answer = answers[name]
    if not answer.found:
        return settings.index_default
    raw = answer.groups[0] if answer.groups else answer.match
    if raw is None:
        return settings.index_default
    try:
        return int(raw) + settings.index_offset
    except TypeError, ValueError:
        return settings.index_default


def _member_record(
    member: dict[str, Any],
    *,
    settings: StackSettings,
    master: dict[str, Any] | None,
    index_answers: Answers,
) -> dict[str, Any]:
    """The shared member record plus this step's stack index and the member's own platform.

    ``platform`` / ``network_driver`` identify the device, not the stack: ``member_bag`` leaves
    them out and ``split-virtual-chassis`` reads them back (W6-12).
    """
    record = member_record(member, master=master)
    platform, network_driver = platform_of(member)
    return {
        **record,
        "platform": platform,
        "network_driver": network_driver,
        settings.index_key: member_index(record["name"], settings, index_answers),
    }


def _unusable_stack_device(
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
        errors=[
            DeviceError(
                node_id=node_id, step_id=STEP_ID, code=code, message=message, failure=MISSING_DATA
            )
        ],
    )


def build_stack_devices(
    vc: dict[str, Any],
    settings: StackSettings,
    *,
    source_id: str,
    node_id: str,
    index_answers: Answers,
) -> list[DeviceContext]:
    """Turn one GraphQL ``virtual_chassis`` object into workflow devices.

    Unsplit: a single device for the whole stack (id of the master member, name of the
    chassis). Split: one device per member, all connecting through the master's IP. A
    stack without a master IP yields ``FAILED`` devices so the executor can route them to
    the ``failure`` outcome.
    """
    vc_id = str(vc.get("id") or "")
    vc_name = str(vc.get("name") or vc_id)
    members = ordered_members(vc)
    master = pick_master(members)
    master_ip = address_of(master)

    if master is None or master_ip is None:
        reason = "has no members" if master is None else "master member has no primary IPv4"
        message = f"Virtual chassis {vc_name!r} {reason}"
        if settings.split_members and members:
            identities = [(str(m.get("id")), str(m.get("name"))) for m in members]
        else:
            identities = [(str(master.get("id")) if master else vc_id, vc_name)]
        return [
            _unusable_stack_device(
                device_id=device_id,
                name=name,
                source_id=source_id,
                node_id=node_id,
                message=message,
                code="no_primary_ip",
            )
            for device_id, name in identities
        ]

    records = [_member_record(m, settings=settings, master=master, index_answers=index_answers)
        for m in members
    ]
    platform_name, network_driver = platform_of(master)
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
        member_platform, member_driver = platform_of(member)
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

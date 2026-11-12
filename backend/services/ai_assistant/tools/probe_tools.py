"""``propose_ping_traceroute``: ask the user to run a ping and/or traceroute from a device (§51).

A proposal, never an execution, on the same signed card and confirm endpoint as §29. The model
names a device, a target IPv4 address, a kind, a VRF, a packet count and an optional source address;
``probes.plan_probes`` writes the commands for the device's platform. The model never writes command
text, and a free-form ``propose_device_command`` still refuses ``ping`` and ``traceroute``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from services.ai_assistant.command_policy import CommandNotAllowedError
from services.ai_assistant.device_access import (
    DeviceAccessError,
    DeviceResolver,
    netmiko_device_type,
)
from services.ai_assistant.neighbors import catalogue
from services.ai_assistant.probes import (
    DEFAULT_COUNT,
    MAX_COUNT,
    UnsupportedProbeError,
    plan_probes,
)
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.device_tools import DEVICE_RESOLVER_KEY, make_device_proposal

DeviceName = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9._-]{1,100}$")
]
VrfName = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9_.-]{1,32}$")
]
Ipv4 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=15)]


class ProposePingTracerouteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: DeviceName = Field(description="Device to probe FROM, as named in the inventory")
    target: Ipv4 = Field(description="The IPv4 address to probe, e.g. '192.168.178.241' (no names)")
    kind: Literal["ping", "traceroute", "both"] = Field(
        default="ping",
        description=(
            "'ping' (the default, for 'can X reach Y'), 'traceroute' only when the user asks for "
            "the path, 'both' when they ask for both"
        ),
    )
    vrf: VrfName = Field(
        default=catalogue.DEFAULT_VRF,
        description="'default' (the global table) or a VRF name the user gave or you read",
    )
    count: int = Field(
        default=DEFAULT_COUNT, ge=1, le=MAX_COUNT, description="Ping packets (1 to 10)"
    )
    source: Ipv4 | None = Field(
        default=None,
        description=(
            "Leave unset unless the user named an address of that device to probe from; never "
            "copy an address from earlier output"
        ),
    )


async def _propose(ctx: ToolContext, args: ProposePingTracerouteInput) -> ToolOutput:
    resolver: DeviceResolver = ctx.extras[DEVICE_RESOLVER_KEY]
    try:
        device = await resolver.resolve(args.device)
    except DeviceAccessError as exc:
        return ToolOutput(str(exc), is_error=True)
    family = catalogue.family_of(netmiko_device_type(device.network_driver, device.platform))
    try:
        if family is None:
            raise UnsupportedProbeError(
                "Ping and traceroute support Cisco IOS / IOS-XE, NX-OS, IOS-XR, Arista EOS and "
                "Junos, and the inventory names none of them for this device"
            )
        commands = plan_probes(family, args.kind, args.target, args.vrf, args.count, args.source)
    except (UnsupportedProbeError, CommandNotAllowedError) as exc:
        return ToolOutput(f"Not possible: {exc}", is_error=True)
    purpose = (
        f"These probes run FROM {device.name} to {args.target}; the commands come from a reviewed "
        "list. After the run read the raw handle with fetch_slice and report what the output shows "
        "(loss, round-trip times, the hop where a traceroute stops). Never invent output."
    )
    return make_device_proposal(ctx, device, commands, "none", purpose=purpose)


_DESCRIPTION = (
    "Ask the user to run a ping and/or traceroute FROM one inventory device TO an IPv4 address, "
    "for questions such as 'can LAB reach 192.168.178.241?'. This only proposes: nothing runs "
    "until the user confirms in the card. You pass the device, target, kind, VRF and count; the "
    "tool writes the platform's commands. Names and IPv6 are not supported; loopback, multicast "
    "and link-local targets are refused."
)


def build_probe_tools() -> list[Tool]:
    return [
        Tool(
            "propose_ping_traceroute",
            _DESCRIPTION,
            ProposePingTracerouteInput,
            _propose,
        )
    ]

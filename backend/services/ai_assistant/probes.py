"""The reviewed ping and traceroute commands per platform (doc/AI_TOOL_CHAIN.md §51).

The one source of probe commands for ``propose_ping_traceroute``: the model chooses a target
address, a VRF, a packet count and a kind from closed values, never command text. Each platform
family spells VRF, count and source its own way. Every ping is bounded in packets (Junos pings
forever without ``count``) and the traceroute of IOS, IOS-XR and Junos in time and hops, without
name lookups. NX-OS and EOS have no such options in the CLI (``UNBOUNDED_TRACEROUTE_FAMILIES``):
their traceroute is bounded only
by the read timeout; on a timeout the run is interrupted (Ctrl-^, Ctrl-C) and the hops printed so
far are kept (``NetmikoDeviceSession._send_interruptible``), so the assistant can still report where
the trace stops. The tool proposes traceroute there only when the user asked for a path. A test
checks that every built command passes ``command_policy.check_probe_command``.

Platforms without an entry (Comware, ASA, ...) are refused with a fixed message. IPv4 only.
"""

from __future__ import annotations

import re
from typing import Literal

from services.ai_assistant.command_policy import (
    CommandNotAllowedError,
    check_probe_command,
    check_probe_target,
)
from services.ai_assistant.neighbors.catalogue import DEFAULT_VRF, FAMILIES

ProbeKind = Literal["ping", "traceroute", "both"]

DEFAULT_COUNT = 5
MAX_COUNT = 10
_VRF = re.compile(r"[A-Za-z0-9_.-]{1,32}")


# Families whose exec traceroute has no timeout, probe-count or TTL option (REVIEW.md, issue 1).
UNBOUNDED_TRACEROUTE_FAMILIES: tuple[str, ...] = ("nxos", "eos")


class UnsupportedProbeError(ValueError):
    """The platform has no catalogued probe command; the message is safe to show."""


def _vrf_tokens(family: str, vrf: str) -> list[str]:
    if vrf == DEFAULT_VRF:
        return []
    return ["routing-instance", vrf] if family == "junos" else ["vrf", vrf]


def _source_tokens(source: str | None) -> list[str]:
    return ["source", source] if source else []


def _ping(family: str, target: str, vrf: str, count: int, source: str | None) -> str:
    v, s = _vrf_tokens(family, vrf), _source_tokens(source)
    if family == "ios":
        parts = ["ping", *v, target, "repeat", str(count), "timeout", "2", *s]
    elif family == "nxos":
        parts = ["ping", target, "count", str(count), "timeout", "2", *v, *s]
    elif family == "xr":
        parts = ["ping", *v, target, "count", str(count), "timeout", "2", *s]
    elif family == "eos":
        parts = ["ping", *v, target, "repeat", str(count), *s]
    elif family == "junos":  # without ``count`` it never stops
        parts = ["ping", target, "count", str(count), *v, *s, "no-resolve"]
    else:
        raise UnsupportedProbeError(f"no ping command is catalogued for {family}")
    return " ".join(parts)


def _traceroute(family: str, target: str, vrf: str, source: str | None) -> str:
    v, s = _vrf_tokens(family, vrf), _source_tokens(source)
    if family == "ios":
        parts = [
            "traceroute",
            *v,
            target,
            "numeric",
            "timeout",
            "1",
            "probe",
            "1",
            "ttl",
            "1",
            "30",
            *s,
        ]
    elif family == "xr":
        # numeric: no reverse DNS lookups from the device; at most 20 hops of 1 probe, 1 s each
        parts = ["traceroute", *v, target, "numeric", "timeout", "1", "probe", "1", "maxttl", "20"]
        parts += s
    elif family in UNBOUNDED_TRACEROUTE_FAMILIES:
        parts = (
            ["traceroute", target, *v, *s] if family == "nxos" else ["traceroute", *v, target, *s]
        )
    elif family == "junos":
        parts = ["traceroute", target, *v, *s, "no-resolve", "wait", "1"]
    else:
        raise UnsupportedProbeError(f"no traceroute command is catalogued for {family}")
    return " ".join(parts)


def plan_probes(
    family: str,
    kind: ProbeKind,
    target: str,
    vrf: str,
    count: int,
    source: str | None,
) -> list[str]:
    """The checked probe commands for ``kind`` on a platform ``family``."""
    if family not in FAMILIES:
        raise UnsupportedProbeError(
            "Ping and traceroute support Cisco IOS / IOS-XE, NX-OS, IOS-XR, Arista EOS and Junos"
        )
    address = check_probe_target(target)
    source_address = check_probe_target(source) if source else None
    if not _VRF.fullmatch(vrf):
        raise CommandNotAllowedError("the VRF name contains unsafe characters")
    if not 1 <= count <= MAX_COUNT:
        raise CommandNotAllowedError(f"count must be between 1 and {MAX_COUNT}")
    commands: list[str] = []
    if kind in ("ping", "both"):
        commands.append(_ping(family, address, vrf, count, source_address))
    if kind in ("traceroute", "both"):
        commands.append(_traceroute(family, address, vrf, source_address))
    return [check_probe_command(c) for c in commands]

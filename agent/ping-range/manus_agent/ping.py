"""The ping logic behind the ``ping_range`` handler (``handlers/ping_range.py`` is a thin wrapper).

One call pings one range with fping and answers, per host: reachable, average round-trip time,
packet loss and (optionally) the reverse-DNS name. Only reachable hosts are listed unless
``include_unreachable`` is set, because the step accepts at most 64 KiB per output value.
"""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from manus_agent.fping import FpingError, HostResult, run_fping
from manus_agent.ranges import IPv4Network, RangeError, expand_ranges, parse_networks
from manus_agent.reverse_dns import resolve_names

DEFAULT_RANGE_ATTRIBUTE = "range"
DEFAULT_MAX_HOSTS = 4096
# Without MANUS_AGENT_PING_ALLOWED_NETWORKS the agent scans private (RFC 1918) space only; a
# workflow author chooses the range, so reaching the internet must be an explicit operator choice
# (for example 0.0.0.0/0).
DEFAULT_ALLOWED_NETWORKS = parse_networks("10.0.0.0/8,172.16.0.0/12,192.168.0.0/16")
MAX_HOSTS_CEILING = 65_536
# The step refuses a value above STEP_OUTPUT_VALUE_MAX_BYTES (64 KiB); stay well below it.
MAX_HOSTS_JSON_BYTES = 60_000

_KNOWN_PARAMS = frozenset(
    {
        "range_attribute",
        "resolve_dns",
        "count",
        "timeout_ms",
        "include_unreachable",
        "dns_timeout_seconds",
    }
)


@dataclass(frozen=True)
class PingSettings:
    """What the operator of this agent host decides (environment), not the workflow author."""

    max_hosts: int
    allowed: tuple[IPv4Network, ...]


def settings_from_env(env: Mapping[str, str]) -> PingSettings:
    raw = env.get("MANUS_AGENT_PING_MAX_HOSTS", "").strip()
    try:
        max_hosts = int(raw) if raw else DEFAULT_MAX_HOSTS
    except ValueError as exc:
        raise ValueError("MANUS_AGENT_PING_MAX_HOSTS must be a whole number") from exc
    if not 1 <= max_hosts <= MAX_HOSTS_CEILING:
        raise ValueError(f"MANUS_AGENT_PING_MAX_HOSTS must be between 1 and {MAX_HOSTS_CEILING}")
    try:
        allowed = parse_networks(env.get("MANUS_AGENT_PING_ALLOWED_NETWORKS"))
        allowed = allowed or DEFAULT_ALLOWED_NETWORKS
    except ValueError as exc:
        raise ValueError(
            "MANUS_AGENT_PING_ALLOWED_NETWORKS must be a comma separated list of IPv4 networks"
        ) from exc
    return PingSettings(max_hosts=max_hosts, allowed=allowed)


@dataclass(frozen=True)
class _Params:
    range_attribute: str | None
    resolve_dns: bool
    count: int
    timeout_ms: int
    include_unreachable: bool
    dns_timeout_seconds: float


def _flag(params: Mapping[str, Any], name: str) -> bool:
    value = params.get(name, False)
    if not isinstance(value, bool):
        raise ValueError(f"params.{name} must be true or false")
    return value


def _number(
    params: Mapping[str, Any], name: str, default: float, low: float, high: float, *, whole: bool
) -> float:
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int if whole else (int, float)):
        raise ValueError(f"params.{name} must be {'a whole ' if whole else 'a '}number")
    if not low <= value <= high:
        raise ValueError(f"params.{name} must be between {low:g} and {high:g}")
    return value


def _parse_params(params: Mapping[str, Any]) -> _Params:
    unknown = sorted(set(params) - _KNOWN_PARAMS)
    if unknown:
        raise ValueError(f"unknown params: {', '.join(map(str, unknown))[:100]}")
    attribute = params.get("range_attribute")
    if attribute is not None and (not isinstance(attribute, str) or not attribute.strip()):
        raise ValueError("params.range_attribute must be a non-empty text")
    return _Params(
        range_attribute=attribute.strip() if attribute else None,
        resolve_dns=_flag(params, "resolve_dns"),
        count=int(_number(params, "count", 1, 1, 5, whole=True)),
        timeout_ms=int(_number(params, "timeout_ms", 500, 50, 5000, whole=True)),
        include_unreachable=_flag(params, "include_unreachable"),
        dns_timeout_seconds=float(_number(params, "dns_timeout_seconds", 2, 0.5, 10, whole=False)),
    )


def _fit(hosts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """The longest prefix of *hosts* whose JSON stays below ``MAX_HOSTS_JSON_BYTES``."""
    size = 2  # "[]"
    for index, host in enumerate(hosts):
        size += len(json.dumps(host, separators=(",", ":"))) + 1
        if size > MAX_HOSTS_JSON_BYTES:
            return hosts[:index], True
    return hosts, False


def _range_text(attribute: str | None, attributes: Mapping[str, Any]) -> Any:
    """The named input path, else the only attribute sent, else the one called ``range``."""
    if attribute is not None:
        if attribute not in attributes:
            raise ValueError(f"the range is missing (input path {attribute!r} was not sent)")
        return attributes[attribute]
    if len(attributes) == 1:
        return next(iter(attributes.values()))
    if DEFAULT_RANGE_ATTRIBUTE in attributes:
        return attributes[DEFAULT_RANGE_ATTRIBUTE]
    raise ValueError(
        "the range is missing: send exactly one input path, or name it in params.range_attribute"
    )


async def _check_icmp_works(timeout_ms: int) -> None:
    """Tell "nothing answered" from "fping cannot send".

    Without the NET_RAW capability (or with ``no-new-privileges`` hiding fping's file capability)
    fping may report 100 % loss for every host and exit normally. When nothing answered, probe the
    loopback address, which always answers if ICMP works at all.
    """
    probe = await run_fping(["127.0.0.1"], count=1, timeout_ms=timeout_ms)
    if not any(r.reachable for r in probe):
        raise FpingError(
            "fping cannot send ICMP from this agent (not even to 127.0.0.1): the container needs "
            "the NET_RAW capability and must not run with no-new-privileges"
        )


async def ping_range(
    params: Mapping[str, Any], inputs: Mapping[str, Any], settings: PingSettings
) -> dict[str, Any]:
    options = _parse_params(params)
    attributes = inputs.get("attributes", {})
    if not isinstance(attributes, Mapping):
        raise ValueError("inputs.attributes must be a JSON object")
    text = _range_text(options.range_attribute, attributes)
    try:
        addresses = expand_ranges(text, max_hosts=settings.max_hosts, allowed=settings.allowed)
    except RangeError as exc:
        raise ValueError(str(exc)) from exc

    reported = {
        result.ip: result
        for result in await run_fping(addresses, count=options.count, timeout_ms=options.timeout_ms)
    }
    # fping reports every host it was given; a missing line is treated as "did not answer".
    results = [reported.get(ip) or HostResult(ip, False, None, 100) for ip in addresses]
    reachable = [r for r in results if r.reachable]
    if not reachable:
        await _check_icmp_works(options.timeout_ms)

    names: dict[str, str | None] = {}
    if options.resolve_dns and reachable:
        names = await resolve_names([r.ip for r in reachable], timeout=options.dns_timeout_seconds)

    listed = results if options.include_unreachable else reachable
    entries = [
        {
            "ip": r.ip,
            "reachable": r.reachable,
            "rtt_ms": r.rtt_ms,
            "loss_percent": r.loss_percent,
            "hostname": names.get(r.ip),
        }
        for r in sorted(listed, key=lambda r: int(ipaddress.IPv4Address(r.ip)))
    ]
    hosts, truncated = _fit(entries)
    return {
        "hosts": hosts,
        "total": len(addresses),
        "reachable": len(reachable),
        "truncated": truncated,
    }

"""The logic behind the ``list_devices`` handler.

The step sends ``tag``. The agent reads the IPv4 prefixes with that tag from Nautobot, pings each
with fping, optionally looks up names and answers ``{"devices": [...]}``, the rows of the *Get from
Agent* step. Anything that would make the inventory incomplete (an oversized or disallowed prefix,
Nautobot or fping failing) is an error: the step must never run on a partial inventory. IPv6
prefixes are skipped (fping is used for IPv4 only) and logged.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import threading
from collections.abc import Mapping
from typing import Any

from manus_agent.fping import FpingError, HostResult, run_fping
from manus_agent.hostpolicy import usable_device_name
from manus_agent.inventory_config import InventoryConfig
from manus_agent.nautobot import fetch_prefixes_by_tag
from manus_agent.ranges import RangeError, expand_ranges
from manus_agent.reverse_dns import resolve_names

logger = logging.getLogger(__name__)

SUPPORTED_ATTRIBUTES = ("tag",)
MAX_TAG_CHARS = 64
# Get from Agent refuses more than this many devices (workflow_steps/get_from_agent/executor.py).
MAX_DEVICES = 5000
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _tag(attributes: Any) -> str:
    if not isinstance(attributes, Mapping):
        raise ValueError("inputs.attributes must be a JSON object")
    unknown = sorted(str(name) for name in set(attributes) - set(SUPPORTED_ATTRIBUTES))
    if unknown:
        raise ValueError(
            f"unsupported attribute: {', '.join(unknown)[:100]} "
            f"(supported: {', '.join(SUPPORTED_ATTRIBUTES)})"
        )
    tag = attributes.get("tag")
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError("the attribute 'tag' is required (the name of a Nautobot tag)")
    tag = tag.strip()
    if len(tag) > MAX_TAG_CHARS or _CONTROL.search(tag):
        raise ValueError(
            f"the tag must be at most {MAX_TAG_CHARS} characters, without control characters"
        )
    return tag


class _DnsStats:
    """What the reverse lookups of one scan did, so the log can say why a name is missing."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counts: dict[str, int] = {}
        self.examples: dict[str, str] = {}

    def add(self, kind: str, exc: Exception | None = None) -> None:
        with self._lock:
            self.counts[kind] = self.counts.get(kind, 0) + 1
            if exc is not None:
                # The text of a socket error names the resolver problem; it holds no secret.
                self.examples.setdefault(kind, f"{type(exc).__name__}: {exc}"[:120])

    def total(self) -> int:
        return sum(self.counts.values())


# h_errno values of gethostbyaddr: 1 HOST_NOT_FOUND and 4 NO_DATA mean the server answered "no such
# record"; 2 TRY_AGAIN (a server failure or no answer) and 3 NO_RECOVERY mean the lookup itself
# failed.
_NO_RECORD_ERRNOS = (1, 4)


def _herror_kind(exc: socket.herror) -> str:
    code = exc.args[0] if exc.args else None
    return "no_ptr_record" if code in _NO_RECORD_ERRNOS else "resolver_error"


def _recording_lookup(stats: _DnsStats):
    """``gethostbyaddr`` that records its outcome; the error still goes to ``resolve_names``."""

    def lookup(ip: str) -> str:
        try:
            name = socket.gethostbyaddr(ip)[0]
        except socket.herror as exc:
            stats.add(_herror_kind(exc), exc)
            raise
        except socket.gaierror as exc:  # the resolver itself failed or could not be reached
            stats.add("resolver_error", exc)
            raise
        except (OSError, UnicodeError, ValueError) as exc:
            stats.add("other_error", exc)
            raise
        stats.add("resolved")
        return name

    return lookup


def _log_dns(stats: _DnsStats, asked: int, names: dict[str, str | None]) -> None:
    resolved = sum(1 for name in names.values() if name)
    detail = ", ".join(f"{kind}={count}" for kind, count in sorted(stats.counts.items()))
    # Lookups that never reported back were still queued or running when their deadline passed.
    unfinished = max(0, asked - stats.total())
    logger.info(
        "reverse DNS: %d of %d named (%s%s)",
        resolved,
        asked,
        detail or "no lookup finished",
        f", timed_out_or_skipped={unfinished}" if unfinished else "",
    )
    for kind, example in sorted(stats.examples.items()):
        logger.info("reverse DNS %s, for example: %s", kind, example)
    if asked and not resolved:
        logger.warning(
            "reverse DNS named none of %d hosts: the DNS server used by this container has no PTR "
            "records for them, cannot be reached, or is too slow (resolve_dns.timeout_seconds)",
            asked,
        )


async def _check_icmp_works(timeout_ms: int) -> None:
    """Tell "nothing answered" from "fping cannot send" (missing NET_RAW).

    127.0.0.1 always answers when ICMP works at all.
    """
    probe = await run_fping(["127.0.0.1"], count=1, timeout_ms=timeout_ms)
    if not any(r.reachable for r in probe):
        raise FpingError(
            "fping cannot send ICMP from this agent (not even to 127.0.0.1): the container needs "
            "the NET_RAW capability and must not run with no-new-privileges"
        )


def _plan(prefixes: list[str], config: InventoryConfig) -> list[list[str]]:
    """The addresses to ping per IPv4 prefix, all checked before the first packet is sent."""
    plan: list[list[str]] = []
    seen: set[str] = set()
    skipped_v6 = 0
    for prefix in prefixes:
        try:
            network = ipaddress.ip_network(prefix, strict=False)
        except ValueError as exc:
            raise ValueError("Nautobot returned a prefix that is not a network") from exc
        if network.version != 4:
            skipped_v6 += 1
            continue
        try:
            addresses = expand_ranges(
                str(network), max_hosts=config.scan.max_hosts, allowed=config.scan.allowed
            )
        except RangeError as exc:
            # The prefix goes to the agent log only: the error reaches the workflow run, whose user
            # must not learn prefixes this agent was configured not to scan.
            logger.warning("prefix %s refused: %s", network, exc)
            raise ValueError(f"a tagged prefix is refused: {exc}") from exc
        fresh = [ip for ip in addresses if ip not in seen]  # overlapping prefixes
        seen.update(fresh)
        if len(seen) > config.scan.max_hosts:
            raise ValueError(
                f"the prefixes hold more than {config.scan.max_hosts} addresses "
                "(the limit of this agent, scan.max_hosts)"
            )
        plan.append(fresh)
    if skipped_v6:
        logger.info("skipped %d IPv6 prefix(es): only IPv4 is scanned", skipped_v6)
    return plan


async def list_devices(
    params: Mapping[str, Any], inputs: Mapping[str, Any], config: InventoryConfig
) -> dict[str, Any]:
    del params  # the request is the attributes only
    tag = _tag(inputs.get("attributes", {}))
    prefixes = await fetch_prefixes_by_tag(config.nautobot, tag)
    if not prefixes:
        raise ValueError(f"no Nautobot prefix carries the tag {tag!r}")
    plan = _plan(prefixes, config)
    if not any(plan):
        raise ValueError(f"no IPv4 prefix carries the tag {tag!r}")

    reachable: list[str] = []
    for addresses in plan:
        if not addresses:
            continue
        results = await run_fping(
            addresses, count=config.scan.count, timeout_ms=config.scan.timeout_ms
        )
        reachable.extend(r.ip for r in results if isinstance(r, HostResult) and r.reachable)
    if not reachable:
        await _check_icmp_works(config.scan.timeout_ms)
    reachable.sort(key=lambda ip: int(ipaddress.IPv4Address(ip)))
    if len(reachable) > MAX_DEVICES:
        raise ValueError(f"{len(reachable)} hosts answered; the limit is {MAX_DEVICES} devices")

    names: dict[str, str | None] = {}
    if config.dns.enabled and reachable:
        stats = _DnsStats()
        names = await resolve_names(
            reachable, timeout=config.dns.timeout_seconds, lookup=_recording_lookup(stats)
        )
        _log_dns(stats, len(reachable), names)
    logger.info("tag scan finished prefixes=%d reachable=%d", len(plan), len(reachable))
    devices = []
    rejected = 0
    for ip in reachable:
        name = names.get(ip)
        if name and not usable_device_name(name):
            rejected += 1  # an odd PTR record: the address is the name
            name = None
        devices.append({"name": name or ip, "ip_address": ip, "network_driver": ""})
    if rejected:
        logger.info(
            "reverse DNS: %d name(s) are not usable host names; the address is used", rejected
        )
    return {"devices": devices}

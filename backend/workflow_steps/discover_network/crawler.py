"""Breadth-first walk of the discover-network step.

Pure with respect to I/O: the caller injects ``visit`` (log into one device, read its CDP
neighbours, log out). A visit that fails raises ``VisitError``; anything else is a bug and
propagates. The walk keeps the visited set, the queue and the reason every neighbour that
was not followed was left out, as the product owner described it: known list, visited list,
next device that is known but not visited.
"""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field

from models.failure import FailureInfo
from workflow_steps.discover_network.parsing import Neighbor, neighbor_device_type
from workflow_steps.discover_network.scope import Prefixes, in_scope

# Closed vocabulary: why a neighbour that was seen was not logged into.
REASON_FOLLOW_DISABLED = "follow_disabled"
REASON_NO_IP = "no_management_ip"
REASON_NOT_INFRASTRUCTURE = "not_infrastructure"
REASON_OUT_OF_SCOPE = "out_of_scope"
REASON_UNSUPPORTED = "unsupported_platform"
REASON_LIMIT = "limit_reached"
REASON_UNREACHABLE = "unreachable"
REASON_LOGIN_FAILED = "login_failed"

LIMIT_MAX_DEVICES = "max_devices"
LIMIT_MAX_DEPTH = "max_depth"


class VisitError(Exception):
    """One device could not be visited; ``code`` is a reason from the closed vocabulary."""

    def __init__(self, code: str, failure: FailureInfo | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.failure = failure


@dataclass(frozen=True)
class Target:
    """A device to log into: a seed from the workflow, or a neighbour that was followed."""

    name: str
    host: str
    device_type: str
    depth: int
    discovered_from: str | None
    seed_id: str | None = None  # the context device id, for seeds only


@dataclass(frozen=True)
class Reading:
    """What one visit read: the neighbours and the CDP status (``ok``, ``not_enabled``, ...).

    A device that was reached but gave no usable CDP data is still a visited device.
    """

    neighbors: tuple[Neighbor, ...]
    status: str = "ok"


@dataclass(frozen=True)
class Visited:
    target: Target
    neighbors: tuple[Neighbor, ...]
    status: str = "ok"


@dataclass(frozen=True)
class Seen:
    """A device that was reported but not logged into, and why."""

    name: str
    ip: str | None
    platform: str
    reason: str
    seen_from: str
    depth: int
    reported_ip: str | None = None  # the interface address CDP reported, if replaced
    ip_source: str = "cdp"


@dataclass(frozen=True)
class Edge:
    from_name: str
    local_port: str
    to_name: str
    remote_port: str
    to_ip: str | None
    reported_ip: str | None = None
    ip_source: str = "cdp"


@dataclass(frozen=True)
class CrawlSettings:
    follow: bool
    prefixes: Prefixes
    only_infrastructure: bool
    max_devices: int
    max_depth: int
    concurrency: int
    override: str | None
    host_policy: Callable[[str], None]


@dataclass(frozen=True)
class CrawlResult:
    visited: tuple[Visited, ...]
    failed_seeds: tuple[tuple[Target, VisitError], ...]
    seen: tuple[Seen, ...]
    edges: tuple[Edge, ...]
    limits_hit: tuple[str, ...]


VisitFn = Callable[[Target], Awaitable[Reading]]
# Looks up the management address of a neighbour (Nautobot) and returns the neighbour with that
# address in ``ip``. It never raises: when nothing is found it returns the neighbour unchanged.
ResolveFn = Callable[[Neighbor], Awaitable[Neighbor]]


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _names_match(left: str, right: str) -> bool:
    """Whether two device names can be the same device.

    Equal names match. If both carry a domain they must be equal (``core1.a.example`` and
    ``core1.b.example`` are two devices); a bare name matches the first label of a qualified one.
    """
    a, b = left.strip().lower(), right.strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    if "." in a and "." in b:
        return False
    return a.split(".", 1)[0] == b.split(".", 1)[0]


@dataclass
class _State:
    """Mutable walk state. The management IP identifies a device.

    A name only recognises a device that has no IP to compare: a seed that was given by host
    name (``unresolved``), and a neighbour that reported no address.
    """

    settings: CrawlSettings
    known_ips: set[str] = field(default_factory=set)
    aliases: list[str] = field(default_factory=list)  # every queued target's name and host name
    # (display name, SSH host name) of targets reached by name, not by IP
    unresolved: list[tuple[str, str]] = field(default_factory=list)
    seen_without_ip: list[str] = field(default_factory=list)
    count: int = 0
    visited: list[Visited] = field(default_factory=list)
    failed: list[tuple[Target, VisitError]] = field(default_factory=list)
    seen: list[Seen] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    limits: list[str] = field(default_factory=list)

    def register(self, target: Target) -> None:
        """Record a target that is queued: its IP, or its names when it was given by name."""
        self.count += 1
        self.aliases.append(target.name)
        if _is_ip(target.host):
            self.known_ips.add(target.host)
        else:
            self.aliases.append(target.host)
            self.unresolved.append((target.name, target.host))

    def is_duplicate_seed(self, target: Target) -> bool:
        if _is_ip(target.host):
            return target.host in self.known_ips
        return any(_names_match(target.host, host) for _, host in self.unresolved)

    def is_known(self, neighbor: Neighbor) -> bool:
        if neighbor.ip is not None:
            return neighbor.ip in self.known_ips or self._is_unresolved_target(neighbor.name)
        # No address to compare: it is a device we already have if its name says so.
        return any(
            _names_match(neighbor.name, name) for name in (*self.aliases, *self.seen_without_ip)
        )

    def _is_unresolved_target(self, name: str) -> bool:
        """The SSH host name decides; the display name only counts when it is exactly the same."""
        return any(
            _names_match(name, host) or name.strip().lower() == display.strip().lower()
            for display, host in self.unresolved
        )

    def _forget_unaddressed(self, name: str) -> None:
        """A device that was first reported without an address now has one: drop the old row."""
        self.seen = [
            row
            for row in self.seen
            if not (row.ip is None and row.reason == REASON_NO_IP and _names_match(row.name, name))
        ]
        self.seen_without_ip = [n for n in self.seen_without_ip if not _names_match(n, name)]

    def hit(self, limit: str) -> None:
        if limit not in self.limits:
            self.limits.append(limit)

    def mark_seen(self, neighbor: Neighbor, reason: str, origin: Target) -> None:
        if neighbor.ip is not None:
            self._forget_unaddressed(neighbor.name)
            self.known_ips.add(neighbor.ip)
        else:
            self.seen_without_ip.append(neighbor.name)
        self.seen.append(
            Seen(
                name=neighbor.name,
                ip=neighbor.ip,
                platform=neighbor.platform,
                reason=reason,
                seen_from=origin.name,
                depth=origin.depth + 1,
                reported_ip=neighbor.reported_ip,
                ip_source=neighbor.ip_source,
            )
        )

    def decide(self, neighbor: Neighbor, origin: Target) -> Target | None:
        """A target to queue, or ``None`` after recording why the neighbour is left out."""
        cfg = self.settings
        depth = origin.depth + 1
        reason = self._skip_reason(neighbor, depth)
        if reason is not None:
            self.mark_seen(neighbor, reason, origin)
            return None
        device_type = neighbor_device_type(neighbor, override=cfg.override)
        if device_type is None or neighbor.ip is None:  # pragma: no cover  (checked above)
            self.mark_seen(neighbor, REASON_UNSUPPORTED, origin)
            return None
        self._forget_unaddressed(neighbor.name)
        target = Target(
            name=neighbor.name,
            host=neighbor.ip,
            device_type=device_type,
            depth=depth,
            discovered_from=origin.name,
        )
        self.register(target)
        return target

    def wants_resolution(self, neighbor: Neighbor) -> bool:
        """Whether the neighbour could be logged into, so its management address is worth a lookup.

        Checks everything that does not depend on the address; scope and limits are decided
        later, on the address the lookup returns.
        """
        cfg = self.settings
        if not cfg.follow:
            return False
        if cfg.only_infrastructure and not neighbor.is_infrastructure:
            return False
        return neighbor_device_type(neighbor, override=cfg.override) is not None

    def _skip_reason(self, neighbor: Neighbor, depth: int) -> str | None:
        cfg = self.settings
        if neighbor.ip is None:
            return REASON_NO_IP
        if cfg.only_infrastructure and not neighbor.is_infrastructure:
            return REASON_NOT_INFRASTRUCTURE
        if not cfg.follow:
            return REASON_FOLLOW_DISABLED
        if not in_scope(neighbor.ip, cfg.prefixes) or not self._host_allowed(neighbor.ip):
            return REASON_OUT_OF_SCOPE
        if neighbor_device_type(neighbor, override=cfg.override) is None:
            return REASON_UNSUPPORTED
        if depth > cfg.max_depth:
            self.hit(LIMIT_MAX_DEPTH)
            return REASON_LIMIT
        if self.count >= cfg.max_devices:
            self.hit(LIMIT_MAX_DEVICES)
            return REASON_LIMIT
        return None

    def _host_allowed(self, host: str) -> bool:
        try:
            self.settings.host_policy(host)
        except ValueError:
            return False
        return True


async def _visit_level(
    frontier: Iterable[Target], visit: VisitFn, concurrency: int
) -> list[tuple[Target, Reading | VisitError]]:
    gate = asyncio.Semaphore(concurrency)

    async def one(target: Target) -> tuple[Target, Reading | VisitError]:
        async with gate:
            try:
                return target, await visit(target)
            except VisitError as exc:
                return target, exc

    return list(await asyncio.gather(*(one(t) for t in frontier)))


async def _resolve_neighbors(
    neighbors: tuple[Neighbor, ...], state: _State, resolve: ResolveFn | None, concurrency: int
) -> tuple[Neighbor, ...]:
    """The neighbours with their management address where the lookup found one."""
    if resolve is None:
        return neighbors
    gate = asyncio.Semaphore(concurrency)

    async def one(neighbor: Neighbor) -> Neighbor:
        if not state.wants_resolution(neighbor):
            return neighbor
        async with gate:
            return await resolve(neighbor)

    return tuple(await asyncio.gather(*(one(n) for n in neighbors)))


async def crawl(
    seeds: list[Target],
    visit: VisitFn,
    settings: CrawlSettings,
    resolve: ResolveFn | None = None,
) -> CrawlResult:
    """Visit the seeds, then every followable neighbour, level by level.

    ``resolve`` swaps a neighbour's interface address for its management address before the
    scope check, the duplicate check and the login, so all three use the address that is dialled.
    """
    state = _State(settings=settings)
    frontier: list[Target] = []
    for seed in seeds:
        if state.is_duplicate_seed(seed):
            continue  # the same device given twice
        state.register(seed)
        frontier.append(seed)

    while frontier:
        results = await _visit_level(frontier, visit, settings.concurrency)
        next_frontier: list[Target] = []
        for target, outcome in results:
            if isinstance(outcome, VisitError):
                if target.seed_id is not None or target.depth == 0:
                    state.failed.append((target, outcome))
                else:
                    state.seen.append(
                        Seen(
                            name=target.name,
                            ip=target.host if _is_ip(target.host) else None,
                            platform="",
                            reason=outcome.code,
                            seen_from=target.discovered_from or "",
                            depth=target.depth,
                        )
                    )
                continue
            neighbors = await _resolve_neighbors(
                outcome.neighbors, state, resolve, settings.concurrency
            )
            state.visited.append(Visited(target, neighbors, outcome.status))
            for neighbor in neighbors:
                state.edges.append(
                    Edge(
                        from_name=target.name,
                        local_port=neighbor.local_port,
                        to_name=neighbor.name,
                        remote_port=neighbor.remote_port,
                        to_ip=neighbor.ip,
                        reported_ip=neighbor.reported_ip,
                        ip_source=neighbor.ip_source,
                    )
                )
                if state.is_known(neighbor):
                    continue
                queued = state.decide(neighbor, target)
                if queued is not None:
                    next_frontier.append(queued)
        frontier = next_frontier

    return CrawlResult(
        visited=tuple(state.visited),
        failed_seeds=tuple(state.failed),
        seen=tuple(state.seen),
        edges=tuple(state.edges),
        limits_hit=tuple(state.limits),
    )

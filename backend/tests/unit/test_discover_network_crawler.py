"""The breadth-first walk of the discover-network step, with a fake network."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from workflow_steps.discover_network.crawler import (
    CrawlSettings,
    Reading,
    Target,
    VisitError,
    crawl,
)
from workflow_steps.discover_network.parsing import Neighbor
from workflow_steps.discover_network.scope import parse_prefixes

IOS = "cisco WS-C3850-48P"
CAPS = ("bridge", "router")


def nb(name: str, ip: str | None, *, platform: str = IOS, caps: tuple[str, ...] = CAPS) -> Neighbor:
    return Neighbor(
        name=name, ip=ip, platform=platform, local_port="Gi1/0/1", remote_port="Gi1/0/2",
        capabilities=caps,
    )  # fmt: skip


@dataclass
class FakeNet:
    """host -> neighbours (or a VisitError); records every visit."""

    links: dict[str, list[Neighbor] | VisitError]
    visits: list[str] = field(default_factory=list)
    running: int = 0
    peak: int = 0

    async def visit(self, target: Target) -> Reading:
        self.visits.append(target.host)
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await asyncio.sleep(0)
            result = self.links.get(target.host, [])
            if isinstance(result, VisitError):
                raise result
            return Reading(tuple(result))
        finally:
            self.running -= 1


def seed(host: str, name: str = "A", device_type: str = "cisco_ios") -> Target:
    return Target(name=name, host=host, device_type=device_type, depth=0, discovered_from=None)


def settings(**over: object) -> CrawlSettings:
    base: dict[str, object] = {
        "follow": True,
        "prefixes": parse_prefixes(["10.1.0.0/16"]),
        "only_infrastructure": True,
        "max_devices": 50,
        "max_depth": 5,
        "concurrency": 3,
        "override": None,
        "host_policy": lambda host: None,
    }
    return CrawlSettings(**{**base, **over})  # type: ignore[arg-type]


def run(net: FakeNet, seeds: list[Target], **over: object):  # noqa: ANN201
    return asyncio.run(crawl(seeds, net.visit, settings(**over)))


def test_walks_a_loop_once_and_in_breadth_first_order() -> None:
    net = FakeNet(
        {
            "10.1.0.1": [nb("B", "10.1.0.2"), nb("C", "10.1.0.3")],
            "10.1.0.2": [nb("A", "10.1.0.1"), nb("C", "10.1.0.3"), nb("D", "10.1.0.4")],
            "10.1.0.3": [nb("A", "10.1.0.1"), nb("B", "10.1.0.2")],
            "10.1.0.4": [nb("B", "10.1.0.2")],
        }
    )
    result = run(net, [seed("10.1.0.1")])
    assert net.visits == ["10.1.0.1", "10.1.0.2", "10.1.0.3", "10.1.0.4"]
    assert [v.target.depth for v in result.visited] == [0, 1, 1, 2]
    assert [v.target.discovered_from for v in result.visited] == [None, "A", "A", "B"]
    assert result.seen == ()
    assert len(result.edges) == 8  # every reported link is kept, visited or not


def test_follow_off_visits_only_the_seeds_and_lists_neighbours() -> None:
    net = FakeNet({"10.1.0.1": [nb("B", "10.1.0.2")]})
    result = run(net, [seed("10.1.0.1")], follow=False)
    assert net.visits == ["10.1.0.1"]
    assert [(s.name, s.reason) for s in result.seen] == [("B", "follow_disabled")]


def test_classifies_neighbours_that_are_not_followed() -> None:
    net = FakeNet(
        {
            "10.1.0.1": [
                nb("noip", None),
                nb("phone", "10.1.0.5", platform="cisco IP Phone", caps=("telephone",)),
                nb("far", "172.16.0.9"),
                nb("linux", "10.1.0.6", platform="Linux"),
                nb("good", "10.1.0.7"),
            ]
        }
    )
    result = run(net, [seed("10.1.0.1")])
    reasons = {s.name: s.reason for s in result.seen}
    assert reasons == {
        "noip": "no_management_ip",
        "phone": "not_infrastructure",
        "far": "out_of_scope",
        "linux": "unsupported_platform",
    }
    assert net.visits == ["10.1.0.1", "10.1.0.7"]


def test_host_policy_failure_is_out_of_scope() -> None:
    def deny(host: str) -> None:
        raise ValueError("no")

    net = FakeNet({"10.1.0.1": [nb("B", "10.1.0.2")]})
    result = run(net, [seed("10.1.0.1")], host_policy=deny)
    assert [(s.name, s.reason) for s in result.seen] == [("B", "out_of_scope")]


def test_infrastructure_filter_can_be_switched_off() -> None:
    phone = nb("phone", "10.1.0.5", caps=("telephone",))
    net = FakeNet({"10.1.0.1": [phone]})
    run(net, [seed("10.1.0.1")], only_infrastructure=False)
    assert "10.1.0.5" in net.visits


def test_max_devices_counts_seeds_and_reports_the_limit() -> None:
    net = FakeNet({"10.1.0.1": [nb("B", "10.1.0.2"), nb("C", "10.1.0.3"), nb("D", "10.1.0.4")]})
    result = run(net, [seed("10.1.0.1")], max_devices=2)
    assert net.visits == ["10.1.0.1", "10.1.0.2"]
    assert {s.name: s.reason for s in result.seen} == {"C": "limit_reached", "D": "limit_reached"}
    assert "max_devices" in result.limits_hit


def test_max_depth_stops_the_walk() -> None:
    net = FakeNet(
        {"10.1.0.1": [nb("B", "10.1.0.2")], "10.1.0.2": [nb("C", "10.1.0.3")]},
    )
    result = run(net, [seed("10.1.0.1")], max_depth=1)
    assert net.visits == ["10.1.0.1", "10.1.0.2"]
    assert [(s.name, s.reason) for s in result.seen] == [("C", "limit_reached")]
    assert "max_depth" in result.limits_hit


def test_a_dead_neighbour_is_seen_not_a_failure_and_the_walk_continues() -> None:
    net = FakeNet(
        {
            "10.1.0.1": [nb("B", "10.1.0.2"), nb("C", "10.1.0.3")],
            "10.1.0.2": VisitError("unreachable"),
            "10.1.0.3": VisitError("login_failed"),
        }
    )
    result = run(net, [seed("10.1.0.1")])
    assert result.failed_seeds == ()
    assert {s.name: s.reason for s in result.seen} == {"B": "unreachable", "C": "login_failed"}
    assert [v.target.name for v in result.visited] == ["A"]


def test_a_dead_seed_is_a_failed_seed() -> None:
    net = FakeNet({"10.1.0.1": VisitError("unreachable"), "10.1.0.9": [nb("B", "10.1.0.2")]})
    result = run(net, [seed("10.1.0.1"), seed("10.1.0.9", "S2")])
    assert [(t.name, e.code) for t, e in result.failed_seeds] == [("A", "unreachable")]
    assert [v.target.name for v in result.visited] == ["S2", "B"]


def test_two_seeds_that_see_each_other_are_visited_once() -> None:
    net = FakeNet(
        {"10.1.0.1": [nb("S2", "10.1.0.2")], "10.1.0.2": [nb("S1", "10.1.0.1")]},
    )
    result = run(net, [seed("10.1.0.1", "S1"), seed("10.1.0.2", "S2")])
    assert sorted(net.visits) == ["10.1.0.1", "10.1.0.2"]
    assert result.seen == ()


def test_a_hostname_seed_is_matched_by_the_name_a_neighbour_reports() -> None:
    net = FakeNet({"core1.example.com": [nb("edge", "10.1.0.2")], "10.1.0.2": [
        nb("core1.example.com", "10.1.0.1")]})  # fmt: skip
    result = run(net, [seed("core1.example.com", "core1")])
    # The neighbour reports the seed's FQDN and an IP: it is the seed, not a new device.
    assert net.visits == ["core1.example.com", "10.1.0.2"]
    assert result.seen == ()


def test_same_short_name_with_different_ips_are_two_devices() -> None:
    net = FakeNet({"10.1.0.1": [nb("sw", "10.1.0.2"), nb("sw", "10.1.0.3")]})
    run(net, [seed("10.1.0.1")])
    assert net.visits == ["10.1.0.1", "10.1.0.2", "10.1.0.3"]


def test_seen_neighbour_is_listed_once_however_often_it_is_reported() -> None:
    far = nb("far", "172.16.0.9")
    net = FakeNet({"10.1.0.1": [far, nb("B", "10.1.0.2")], "10.1.0.2": [far]})
    result = run(net, [seed("10.1.0.1")])
    assert [s.name for s in result.seen] == ["far"]
    assert len([e for e in result.edges if e.to_name == "far"]) == 2


def test_concurrency_is_bounded() -> None:
    hosts = [f"10.1.1.{i}" for i in range(2, 12)]
    net = FakeNet({"10.1.0.1": [nb(f"n{i}", h) for i, h in enumerate(hosts)]})
    run(net, [seed("10.1.0.1")], concurrency=2)
    assert len(net.visits) == 11
    assert net.peak <= 2


def test_override_is_used_for_a_neighbour_without_platform() -> None:
    net = FakeNet({"10.1.0.1": [nb("B", "10.1.0.2", platform="")]})
    seen_types: list[str] = []

    async def visit(target: Target) -> Reading:
        seen_types.append(target.device_type)
        return Reading(tuple(net.links.get(target.host, [])))  # type: ignore[arg-type]

    asyncio.run(crawl([seed("10.1.0.1")], visit, settings(override="cisco_xe")))
    assert seen_types == ["cisco_ios", "cisco_xe"]


def test_unexpected_exception_from_visit_propagates() -> None:
    async def boom(target: Target) -> Reading:
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError):
        asyncio.run(crawl([seed("10.1.0.1")], boom, settings()))


def test_a_reached_device_without_cdp_data_is_still_visited() -> None:
    async def visit(target: Target) -> Reading:
        return Reading((), status="not_enabled")

    result = asyncio.run(crawl([seed("10.1.0.1")], visit, settings()))
    assert [(v.target.name, v.status) for v in result.visited] == [("A", "not_enabled")]
    assert result.failed_seeds == ()


def test_a_later_sighting_with_an_address_is_followed_and_clears_the_stale_row() -> None:
    # CDP often omits the management address on one link and gives it on another.
    net = FakeNet(
        {
            "10.1.0.1": [nb("sw2", None)],
            "10.1.0.2": [nb("sw2.lab.local", "10.1.0.50")],
        }
    )
    result = run(net, [seed("10.1.0.1"), seed("10.1.0.2", "B")])
    assert "10.1.0.50" in net.visits
    assert result.seen == ()  # the "no_management_ip" row for the same device is gone


def test_a_no_address_neighbour_stays_listed_when_nothing_later_gives_one() -> None:
    net = FakeNet({"10.1.0.1": [nb("sw2", None)], "10.1.0.2": [nb("sw2", None)]})
    result = run(net, [seed("10.1.0.1"), seed("10.1.0.2", "B")])
    assert [(s.name, s.reason) for s in result.seen] == [("sw2", "no_management_ip")]


def test_a_different_device_with_the_same_short_name_as_a_seed_is_not_the_seed() -> None:
    net = FakeNet({"core1.example.com": [nb("core1.other-site.example", "10.1.9.9")]})
    run(net, [seed("core1.example.com", "core1")])
    assert net.visits == ["core1.example.com", "10.1.9.9"]


def test_a_hostname_seed_is_recognised_by_its_ssh_host_not_only_its_display_name() -> None:
    net = FakeNet(
        {
            "core1.example.com": [nb("edge", "10.1.0.2")],
            "10.1.0.2": [nb("core1.example.com", "10.1.0.1")],
        }
    )
    result = run(net, [seed("core1.example.com", "Core Switch")])
    assert net.visits == ["core1.example.com", "10.1.0.2"]
    assert [v.target.name for v in result.visited] == ["Core Switch", "edge"]


def test_a_neighbour_without_address_that_names_a_visited_device_is_not_listed() -> None:
    net = FakeNet({"10.1.0.1": [nb("B", "10.1.0.2")], "10.1.0.2": [nb("A", None)]})
    result = run(net, [seed("10.1.0.1", "A")])
    assert result.seen == ()


def test_a_virtual_switch_that_reports_linux_is_followed_by_its_software_line() -> None:
    iosxe = "Cisco IOS Software [IOSXE], Linux Software (X86_64BI_LINUX_L2-ADVENTERPRISEK9-M)"
    vm = Neighbor(
        name="vsw", ip="10.1.0.7", platform="Linux Unix", local_port="a", remote_port="b",
        capabilities=("bridge", "router"), software=iosxe,
    )  # fmt: skip
    net = FakeNet({"10.1.0.1": [vm]})
    types: list[str] = []

    async def visit(target: Target) -> Reading:
        types.append(target.device_type)
        return Reading(tuple(net.links.get(target.host, [])))  # type: ignore[arg-type]

    result = asyncio.run(crawl([seed("10.1.0.1")], visit, settings()))
    assert types == ["cisco_ios", "cisco_xe"]
    assert result.seen == ()

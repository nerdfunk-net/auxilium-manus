"""The Nautobot management-address lookup of the discover-network step, with a fake client."""

from __future__ import annotations

import asyncio
from typing import Any

from nautobot_read.client import NautobotError, Page

from workflow_steps.discover_network.nautobot_lookup import ManagementIpLookup
from workflow_steps.discover_network.parsing import Neighbor


def nb(name: str = "sw2", ip: str | None = "192.168.9.2") -> Neighbor:
    return Neighbor(
        name=name, ip=ip, platform="cisco WS-C3850", local_port="Gi1", remote_port="Gi2",
        capabilities=("router",),
    )  # fmt: skip


def device(name: str, primary: str | None = "10.1.0.2/32") -> dict[str, Any]:
    return {"id": name, "name": name, "primary_ip4": {"address": primary} if primary else None}


class FakeClient:
    """Answers ``list_page`` from tables keyed by (root, filter name, value)."""

    def __init__(self, tables: dict[tuple[str, str, str], list[dict[str, Any]]]) -> None:
        self.tables = tables
        self.calls: list[tuple[str, str, str]] = []
        self.fail = False

    async def list_page(
        self, root: str, selection: str, filters: dict[str, list[str]], *, limit: int, offset: int
    ) -> Page:
        del selection, limit, offset
        ((name, values),) = ((k, v) for k, v in filters.items() if v)
        key = (root, name, values[0])
        self.calls.append(key)
        if self.fail:
            raise NautobotError("Could not reach Nautobot.")
        return Page(items=tuple(self.tables.get(key, [])), has_more=False)


def resolve(client: FakeClient, neighbor: Neighbor) -> tuple[Neighbor, ManagementIpLookup]:
    lookup = ManagementIpLookup(client)
    return asyncio.run(lookup.resolve(neighbor)), lookup


def test_the_name_is_looked_up_first_and_its_primary_ip_is_used() -> None:
    client = FakeClient({("devices", "name", "sw2"): [device("sw2")]})
    result, _ = resolve(client, nb())
    assert (result.ip, result.reported_ip, result.ip_source) == (
        "10.1.0.2", "192.168.9.2", "nautobot_name",
    )  # fmt: skip
    assert result.name == "sw2"
    assert not any(root == "ip_addresses" for root, _, _ in client.calls)


def test_the_name_lookup_ignores_case_then_tries_the_start_of_a_full_name() -> None:
    client = FakeClient({("devices", "name__isw", "sw2."): [device("sw2.lab.example")]})
    result, _ = resolve(client, nb())
    assert result.ip == "10.1.0.2"
    assert [c[1] for c in client.calls] == ["name", "name__ie", "name__isw"]


def test_a_full_name_falls_back_to_its_first_label() -> None:
    client = FakeClient({("devices", "name__ie", "sw2"): [device("sw2")]})
    result, _ = resolve(client, nb(name="sw2.lab.example"))
    assert result.ip == "10.1.0.2"


def test_an_unknown_name_falls_back_to_the_interface_ip_lookup() -> None:
    row = {"address": "192.168.9.2/30", "interfaces": [{"device": device("core-2", "10.1.0.7/32")}]}
    client = FakeClient({("ip_addresses", "address", "192.168.9.2"): [row]})
    result, _ = resolve(client, nb(name="cdp-name"))
    assert (result.ip, result.name, result.ip_source) == ("10.1.0.7", "core-2", "nautobot_ip")
    assert result.reported_ip == "192.168.9.2"


def test_a_name_without_a_primary_ip_falls_back_to_the_interface_ip() -> None:
    row = {"interfaces": [{"device": device("sw2", "10.1.0.8/32")}]}
    client = FakeClient(
        {
            ("devices", "name", "sw2"): [device("sw2", None)],
            ("ip_addresses", "address", "192.168.9.2"): [row],
        }
    )
    result, _ = resolve(client, nb())
    assert (result.ip, result.ip_source) == ("10.1.0.8", "nautobot_ip")


def test_an_ambiguous_name_is_never_guessed() -> None:
    client = FakeClient({("devices", "name", "sw2"): [device("sw2"), device("sw2")]})
    result, _ = resolve(client, nb())
    assert (result.ip, result.ip_source) == ("192.168.9.2", "cdp")


def test_an_address_on_two_devices_is_never_guessed() -> None:
    rows = [{"interfaces": [{"device": device("a")}, {"device": device("b", "10.1.0.9/32")}]}]
    client = FakeClient({("ip_addresses", "address", "192.168.9.2"): rows})
    result, _ = resolve(client, nb(name="x"))
    assert result.ip_source == "cdp"


def test_nothing_found_returns_the_neighbour_unchanged() -> None:
    neighbor = nb()
    result, lookup = resolve(FakeClient({}), neighbor)
    assert result == neighbor
    assert not lookup.unavailable


def test_a_neighbour_without_an_ip_still_gets_a_name_lookup() -> None:
    client = FakeClient({("devices", "name", "sw2"): [device("sw2")]})
    result, _ = resolve(client, nb(ip=None))
    assert (result.ip, result.reported_ip) == ("10.1.0.2", None)


def test_a_nautobot_failure_falls_back_and_is_reported() -> None:
    client = FakeClient({})
    client.fail = True
    neighbor = nb()
    result, lookup = resolve(client, neighbor)
    assert result == neighbor
    assert lookup.unavailable


def test_a_non_ipv4_primary_address_is_ignored() -> None:
    client = FakeClient({("devices", "name", "sw2"): [device("sw2", "2001:db8::1/128")]})
    result, _ = resolve(client, nb())
    assert result.ip_source == "cdp"


def test_the_same_neighbour_is_looked_up_once() -> None:
    client = FakeClient({("devices", "name", "sw2"): [device("sw2")]})
    lookup = ManagementIpLookup(client)

    async def twice() -> None:
        await lookup.resolve(nb())
        await lookup.resolve(nb())

    asyncio.run(twice())
    assert len(client.calls) == 1

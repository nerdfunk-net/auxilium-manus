"""The lookup only builds the data of the MACs a filter can match, and returns the same rows.

Before: every lookup correlated the MAC tables and ARP tables of the whole network and filtered
afterwards, so the work grew with the product of the table sizes (176 million rows thrown away by
join filters on 9,800 MAC and 5,800 ARP rows). The lookup now restricts the correlation to the
MACs that can produce a matching row. The tests prove that this changes the cost, not the answer:
the same call with the restriction switched off is the reference.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import pytest
from _client_data_dataset import Facts, build_dataset
from sqlalchemy import Table, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from test_client_data_query_repository import TABLES, _collect

import repositories.client_data_query_repository as query_module
from core.models.base import Base
from repositories.client_data_query_repository import ClientDataQueryRepository

THRESHOLD = 3  # small, so the generated ports become uplinks by count too


@pytest.fixture(scope="module")
def world() -> Iterator[tuple[Session, Facts, Engine]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[cast("Table", t) for t in TABLES])
    with sessionmaker(bind=engine)() as session:
        facts = build_dataset(_collect, session)
        yield session, facts, engine
    engine.dispose()


def _lookups(f: Facts) -> dict[str, dict[str, Any]]:
    """Filter combinations; every one of them matches something (checked below)."""
    return {
        "ip": {"ip_address": f.ip},
        "ip substring": {"ip_address": "10.1."},
        "ip prefix": {"ip_prefix": "10.0."},
        "ipv6": {"ip_address": f.ipv6},
        "ipv6 other notation": {"ip_address": "2001:0db8:0000:0000:0000:0000:0000:0001"},
        "mac": {"mac_address": f.mac},
        "mac in another notation": {"mac_address": f.mac.upper().replace(".", ":")},
        "mac fragment": {"mac_address": "ccdd.000"},
        "device": {"device_name": f.switch},
        "router": {"device_name": f.router},
        "port": {"port": f.port},
        "interface of an ARP-only row": {"port": "Gi0/0"},
        "vlan": {"vlan": "20"},
        "vrf": {"vrf": "cust"},
        "hostname": {"hostname": f.hostname},
        "hostname fragment": {"hostname": "HOST-ONE"},
        "ip and device": {"ip_address": f.ip, "device_name": f.router},
        "mac and vlan": {"mac_address": f.mac, "vlan": "10"},
        "hostname and vrf": {"hostname": "example", "vrf": "cust"},
        "ip and a device that does not hold it": {"ip_address": f.ip, "device_name": "sw2"},
        "ip and mac of different hosts": {"ip_address": f.ip, "mac_address": "aabb.ccdd.0002"},
        "an IP nobody has": {"ip_address": "192.0.2.77"},
        "a MAC nobody has": {"mac_address": "ffff.ffff.ffff"},
        "a hostname nobody has": {"hostname": "nobody.example.net"},
    }


NO_ANSWER = {"an IP nobody has", "a MAC nobody has", "a hostname nobody has"}
NEEDS_EXACT = {"ipv6 other notation"}  # a substring cannot match another notation
EMPTY_ANYWAY = {"ip and a device that does not hold it", "ip and mac of different hosts"}
NAMES = list(_lookups(Facts("", "", "", "", "", "", "")))


def _ask(session: Session, **kwargs: Any) -> tuple[list[dict[str, Any]], int]:
    repo = ClientDataQueryRepository(session, uplink_threshold=THRESHOLD)
    return repo.get_client_data(page_size=500, **kwargs)


@pytest.mark.parametrize("hide_uplinks", [False, True])
@pytest.mark.parametrize("likely_first", [False, True])
@pytest.mark.parametrize("exact", [False, True])
@pytest.mark.parametrize("name", NAMES)
def test_the_narrowed_lookup_returns_what_the_full_view_returns(
    world: tuple[Session, Facts, Engine],
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    exact: bool,
    likely_first: bool,
    hide_uplinks: bool,
) -> None:
    session, facts, _ = world
    kwargs = {
        **_lookups(facts)[name],
        "exact": exact,
        "likely_first": likely_first,
        "hide_uplinks": hide_uplinks,
    }
    narrowed = _ask(session, **kwargs)
    # The reference: the same call on the whole correlated view, filtered afterwards.
    monkeypatch.setattr(query_module, "_narrowing", lambda *args, **kw: [])
    reference = _ask(session, **kwargs)

    assert narrowed == reference  # rows, order, macs_on_port, uplink flags, total


@pytest.mark.parametrize("name", [n for n in NAMES if n not in NO_ANSWER | EMPTY_ANYWAY])
def test_the_lookups_are_not_vacuous(world: tuple[Session, Facts, Engine], name: str) -> None:
    """A comparison of two empty results proves nothing: the lookups find rows."""
    session, facts, _ = world
    items, total = _ask(session, exact=name in NEEDS_EXACT, **_lookups(facts)[name])

    assert items
    assert total == len(items)


def test_the_dataset_has_what_the_correlation_has_to_cope_with(
    world: tuple[Session, Facts, Engine],
) -> None:
    session, _, _ = world
    items, _ = _ask(session)

    assert any(i["is_uplink"] and i["uplink_reason"] == "neighbor" for i in items)
    assert any(i["is_uplink"] and i["uplink_reason"] == "mac_count" for i in items)
    assert any(i["likely_location"] for i in items)
    assert any(i["ip_address"] is None for i in items)
    assert any(i["vrf"] for i in items)
    assert any(i["hostname"] for i in items)
    assert any(i["macs_on_port"] is None for i in items)  # ARP-only observations
    macs_on_several_devices = {
        m
        for m in {i["mac_address"] for i in items}
        if len({i["device_name"] for i in items if i["mac_address"] == m}) > 1
    }
    assert macs_on_several_devices


@pytest.mark.parametrize("name", NAMES)
def test_every_filter_restricts_the_correlation(
    world: tuple[Session, Facts, Engine], name: str
) -> None:
    session, facts, engine = world
    seen: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        _ask(session, **_lookups(facts)[name])
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert seen
    filters = len(_lookups(facts)[name])
    for statement in seen:
        # mac_entries, arp_entries, ip_in_vlan, ip_without_vlan and ip_any each read only the
        # candidate MACs of every filter; one that does not correlates the whole network again.
        assert statement.count("IN (SELECT candidate_macs_") == 5 * filters


def test_a_lookup_without_a_filter_correlates_everything(
    world: tuple[Session, Facts, Engine],
) -> None:
    session, _, engine = world
    seen: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        _ask(session)
        _ask(session, hide_uplinks=True)  # computed from the correlation: cannot be narrowed
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert seen
    assert not any("candidate_macs" in statement for statement in seen)


def test_the_port_counts_still_cover_every_mac_of_the_port(
    world: tuple[Session, Facts, Engine],
) -> None:
    """``macs_on_port`` counts all MACs a port learned, not only the ones the lookup asked for."""
    session, facts, _ = world
    asked, _ = _ask(session, mac_address=facts.mac, exact=True)
    everything, _ = _ask(session)

    on_port = {
        (i["device_name"], i["port"]): i["macs_on_port"] for i in everything if i["macs_on_port"]
    }
    for row in asked:
        if row["macs_on_port"] is not None:
            assert row["macs_on_port"] == on_port[(row["device_name"], row["port"])]


def test_the_total_follows_the_narrowed_lookup(world: tuple[Session, Facts, Engine]) -> None:
    session, facts, _ = world
    items, total = ClientDataQueryRepository(session, uplink_threshold=THRESHOLD).get_client_data(
        mac_address=facts.mac, exact=True, page_size=1
    )

    assert len(items) == 1
    assert total > 1  # the MAC is on several devices: the count is not cut by the page

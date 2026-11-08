"""Correlated read queries over the client data tables (latest collection per device)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import Table, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.base import Base
from core.models.client_data import (
    ClientDataCollection,
    ClientHostname,
    ClientIpAddress,
    ClientMacAddress,
)
from models.client_data import (
    ClientCollectionStatus,
    ClientHostnameRow,
    ClientIpRow,
    ClientMacRow,
)
from repositories.client_data_query_repository import ClientDataQueryRepository
from repositories.client_data_repository import ClientDataRepository

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
TABLES = [
    cast("Table", model.__table__)
    for model in (ClientIpAddress, ClientMacAddress, ClientHostname, ClientDataCollection)
]
OK = ClientCollectionStatus(arp_status="ok", mac_status="ok", vrf_status="ok")


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=TABLES)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


def _collect(
    db: Session,
    *,
    device: str,
    session_id: str = "run-1",
    at: datetime = NOW,
    ips: list[ClientIpRow] | None = None,
    macs: list[ClientMacRow] | None = None,
    hostnames: list[ClientHostnameRow] | None = None,
    keep: int = 5,
    status: ClientCollectionStatus = OK,
) -> None:
    ClientDataRepository(db).replace_device_collection(
        session_id=session_id,
        device_name=device,
        device_ip=None,
        collected_at=at,
        ip_rows=ips or [],
        mac_rows=macs or [],
        hostname_rows=hostnames or [],
        status=status,
        keep_sessions=keep,
    )


@pytest.fixture
def lab(db: Session) -> Session:
    """core1 (L3: ARP only, VRF CUST) and acc1 (L2: MAC table only)."""
    _collect(
        db,
        device="core1",
        ips=[
            ClientIpRow(
                ip_address="10.0.10.5", mac_address="aabb.ccdd.0001", interface="Vlan10", vlan="10"
            ),
            ClientIpRow(
                ip_address="10.0.20.7",
                mac_address="aabb.ccdd.0002",
                interface="Vlan20",
                vrf="CUST",
                vlan="20",
            ),
        ],
        hostnames=[ClientHostnameRow(ip_address="10.0.10.5", hostname="pc1.example.net")],
    )
    _collect(
        db,
        device="acc1",
        macs=[
            ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/5"),
            ClientMacRow(mac_address="aabb.ccdd.0003", vlan="10", port="Gi1/0/6"),
        ],
    )
    return db


def _by_key(items: list[dict]) -> dict[tuple[str, str], dict]:
    return {(item["mac_address"], item["device_name"]): item for item in items}


def test_correlates_mac_table_arp_and_hostname(lab: Session) -> None:
    items, total = ClientDataQueryRepository(lab).get_client_data()

    assert total == 4
    rows = _by_key(items)
    l2_view = rows[("aabb.ccdd.0001", "acc1")]
    assert (l2_view["port"], l2_view["vlan"], l2_view["vrf"]) == ("Gi1/0/5", "10", None)
    # The L2 switch has no ARP: the IP comes from the L3 device that saw the MAC.
    assert l2_view["ip_address"] == "10.0.10.5"
    assert l2_view["hostname"] == "pc1.example.net"

    l3_view = rows[("aabb.ccdd.0001", "core1")]
    assert (l3_view["port"], l3_view["vlan"]) == ("Vlan10", "10")

    vrf_row = rows[("aabb.ccdd.0002", "core1")]
    assert (vrf_row["vrf"], vrf_row["vlan"], vrf_row["ip_address"]) == ("CUST", "20", "10.0.20.7")

    unknown_ip = rows[("aabb.ccdd.0003", "acc1")]
    assert unknown_ip["ip_address"] is None


def test_only_the_latest_collection_of_each_device_is_shown(lab: Session) -> None:
    # acc1 is collected again later and no longer learns MAC ...0003.
    _collect(
        lab,
        device="acc1",
        session_id="run-2",
        at=NOW + timedelta(hours=1),
        macs=[ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/9")],
    )

    items, _ = ClientDataQueryRepository(lab).get_client_data(mac_address="aabb.ccdd.0003")
    assert items == []
    rows = _by_key(ClientDataQueryRepository(lab).get_client_data()[0])
    assert rows[("aabb.ccdd.0001", "acc1")]["port"] == "Gi1/0/9"
    # core1 was not part of run-2 and is still shown from run-1.
    assert ("aabb.ccdd.0002", "core1") in rows


def test_an_empty_latest_collection_hides_the_older_rows(lab: Session) -> None:
    _collect(lab, device="acc1", session_id="run-2", at=NOW + timedelta(hours=1))

    items, _ = ClientDataQueryRepository(lab).get_client_data(device_name="acc1")
    assert items == []


@pytest.mark.parametrize(
    ("filters", "expected_macs"),
    [
        ({"mac_address": "0002"}, {"aabb.ccdd.0002"}),
        ({"ip_address": "10.0.20"}, {"aabb.ccdd.0002"}),
        ({"vrf": "cust"}, {"aabb.ccdd.0002"}),
        ({"vlan": "20"}, {"aabb.ccdd.0002"}),
        ({"port": "gi1/0/6"}, {"aabb.ccdd.0003"}),
        ({"hostname": "PC1"}, {"aabb.ccdd.0001"}),
        ({"device_name": "acc"}, {"aabb.ccdd.0001", "aabb.ccdd.0003"}),
    ],
)
def test_filters_match_case_insensitive_substrings(
    lab: Session, filters: dict[str, str], expected_macs: set[str]
) -> None:
    items, total = ClientDataQueryRepository(lab).get_client_data(**filters)

    assert {item["mac_address"] for item in items} == expected_macs
    assert total == len(items)


def test_filter_wildcards_in_user_input_are_literal(lab: Session) -> None:
    items, total = ClientDataQueryRepository(lab).get_client_data(mac_address="%")
    assert (items, total) == ([], 0)


def test_pagination_returns_total_and_a_page(lab: Session) -> None:
    repo = ClientDataQueryRepository(lab)
    first, total = repo.get_client_data(page=1, page_size=3)
    second, _ = repo.get_client_data(page=2, page_size=3)

    assert total == 4
    assert (len(first), len(second)) == (3, 1)
    assert {(i["mac_address"], i["device_name"]) for i in first}.isdisjoint(
        {(i["mac_address"], i["device_name"]) for i in second}
    )


def test_device_names_lists_devices_of_the_latest_collections(lab: Session) -> None:
    assert ClientDataQueryRepository(lab).get_device_names() == ["acc1", "core1"]


def test_history_spans_all_retained_collections(lab: Session) -> None:
    _collect(
        lab,
        device="acc1",
        session_id="run-2",
        at=NOW + timedelta(hours=1),
        macs=[ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/9")],
    )

    history = ClientDataQueryRepository(lab).get_client_history(mac_address="aabb.ccdd.0001")

    ports = [(row["device_name"], row["port"]) for row in history["mac_history"]]
    assert ports == [("acc1", "Gi1/0/9"), ("acc1", "Gi1/0/5")]
    assert history["ip_history"] == []
    assert history["hostname_history"] == []


def test_history_by_ip_and_hostname(lab: Session) -> None:
    history = ClientDataQueryRepository(lab).get_client_history(
        ip_address="10.0.10.5", hostname="pc1.example.net"
    )

    (ip_row,) = history["ip_history"]
    assert (ip_row["device_name"], ip_row["mac_address"], ip_row["vlan"]) == (
        "core1",
        "aabb.ccdd.0001",
        "10",
    )
    (host_row,) = history["hostname_history"]
    assert host_row["ip_address"] == "10.0.10.5"


def _extra(db: Session) -> None:
    _collect(
        db,
        device="core2",
        ips=[
            # One NIC with two addresses, and a gateway MAC that exists in two VRFs.
            ClientIpRow(ip_address="10.0.30.1", mac_address="aabb.ccdd.0005", vlan="30"),
            ClientIpRow(ip_address="10.0.30.2", mac_address="aabb.ccdd.0005", vlan="30"),
            ClientIpRow(ip_address="10.9.0.1", mac_address="aabb.ccdd.0007"),
            ClientIpRow(ip_address="10.9.0.1", mac_address="aabb.ccdd.0007", vrf="CUST"),
        ],
    )
    _collect(
        db,
        device="acc2",
        macs=[
            ClientMacRow(mac_address="aabb.ccdd.0006", vlan="10", port="Gi1/0/7"),
            ClientMacRow(mac_address="aabb.ccdd.0006", vlan="20", port="Gi1/0/7"),
        ],
    )


def test_a_mac_with_several_ips_or_vrfs_keeps_every_observation(db: Session) -> None:
    _extra(db)

    items, _ = ClientDataQueryRepository(db).get_client_data(device_name="core2")

    observed = sorted(
        ((i["mac_address"], i["ip_address"], i["vrf"]) for i in items),
        key=lambda row: tuple(str(part) for part in row),
    )
    assert observed == [
        ("aabb.ccdd.0005", "10.0.30.1", None),
        ("aabb.ccdd.0005", "10.0.30.2", None),
        ("aabb.ccdd.0007", "10.9.0.1", "CUST"),
        ("aabb.ccdd.0007", "10.9.0.1", None),
    ]


def test_a_mac_learned_in_two_vlans_keeps_both(db: Session) -> None:
    _extra(db)

    items, _ = ClientDataQueryRepository(db).get_client_data(device_name="acc2")

    assert sorted((i["vlan"], i["port"]) for i in items) == [("10", "Gi1/0/7"), ("20", "Gi1/0/7")]


def test_history_keeps_the_same_ip_in_two_vrfs_and_the_mac_in_two_vlans(db: Session) -> None:
    _extra(db)
    repo = ClientDataQueryRepository(db)

    ip_history = repo.get_client_history(ip_address="10.9.0.1")["ip_history"]
    mac_history = repo.get_client_history(mac_address="aabb.ccdd.0006")["mac_history"]

    assert sorted(str(row["vrf"]) for row in ip_history) == ["CUST", "None"]
    assert sorted(str(row["vlan"]) for row in mac_history) == ["10", "20"]


@pytest.mark.parametrize("typed", ["aa:bb:cc:dd:00:02", "AA-BB-CC-DD-00-02", "aabbccdd0002"])
def test_mac_filter_accepts_other_notations(lab: Session, typed: str) -> None:
    items, _ = ClientDataQueryRepository(lab).get_client_data(mac_address=typed)

    assert {i["mac_address"] for i in items} == {"aabb.ccdd.0002"}


def test_arp_without_a_vlan_does_not_multiply_the_mac_rows(db: Session) -> None:
    # One MAC in two VLANs plus two ARP entries with no VLAN: two MAC observations and two
    # ARP observations, not their product.
    _collect(
        db,
        device="sw",
        macs=[
            ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/1"),
            ClientMacRow(mac_address="aabb.ccdd.0001", vlan="20", port="Gi1/0/2"),
        ],
        ips=[
            ClientIpRow(ip_address="10.1.1.1", mac_address="aabb.ccdd.0001", interface="Gi0/1"),
            ClientIpRow(ip_address="10.1.1.2", mac_address="aabb.ccdd.0001", interface="Gi0/1"),
        ],
    )

    items, total = ClientDataQueryRepository(db).get_client_data()

    assert total == 4 == len(items)
    assert sorted(i["port"] for i in items) == ["Gi0/1", "Gi0/1", "Gi1/0/1", "Gi1/0/2"]


def test_an_ip_seen_in_another_vlan_is_not_attributed_to_the_mac(db: Session) -> None:
    _collect(
        db,
        device="sw9",
        macs=[ClientMacRow(mac_address="aabb.ccdd.0009", vlan="10", port="Gi1/0/9")],
    )
    _collect(
        db,
        device="core",
        ips=[ClientIpRow(ip_address="10.9.9.9", mac_address="aabb.ccdd.0009", vlan="99")],
    )

    items, _ = ClientDataQueryRepository(db).get_client_data(device_name="sw9")

    assert [(i["vlan"], i["port"], i["ip_address"]) for i in items] == [("10", "Gi1/0/9", None)]


def test_an_ip_from_a_routed_neighbour_without_a_vlan_still_fills_the_gap(db: Session) -> None:
    _collect(
        db,
        device="sw1",
        macs=[ClientMacRow(mac_address="aabb.ccdd.0009", vlan="10", port="Gi1/0/9")],
    )
    _collect(
        db,
        device="router",
        ips=[ClientIpRow(ip_address="10.0.0.9", mac_address="aabb.ccdd.0009", interface="Gi0/0")],
    )

    items, _ = ClientDataQueryRepository(db).get_client_data(device_name="sw1")

    assert [i["ip_address"] for i in items] == ["10.0.0.9"]


def test_history_matches_other_mac_notations_and_any_hostname_case(lab: Session) -> None:
    repo = ClientDataQueryRepository(lab)

    by_colon = repo.get_client_history(mac_address="AA:BB:CC:DD:00:01")
    by_host = repo.get_client_history(hostname="PC1.EXAMPLE.NET")

    assert len(by_colon["mac_history"]) == 1
    assert len(by_host["hostname_history"]) == 1


def test_history_is_bounded(db: Session) -> None:
    for index in range(30):
        _collect(
            db,
            device="sw",
            session_id=f"s{index}",
            at=NOW + timedelta(minutes=index),
            macs=[ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/1")],
            keep=50,
        )

    history = ClientDataQueryRepository(db).get_client_history(
        mac_address="aabb.ccdd.0001", limit=10
    )

    assert len(history["mac_history"]) == 10


@pytest.mark.parametrize(
    "kwargs", [{"page": 0}, {"page": -1}, {"page_size": 0}, {"page_size": 100000}]
)
def test_paging_arguments_are_validated(db: Session, kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="page"):
        ClientDataQueryRepository(db).get_client_data(**kwargs)


# --- uplink flagging, exact matching, coverage -------------------------------------------------


def _uplink_lab(db: Session) -> None:
    """swA: Et0/0 is an uplink with 12 MACs. swB: Gi1/0/5 is an access port with 2 MACs."""
    uplink_macs = [
        ClientMacRow(mac_address=f"aabb.0000.{n:04x}", vlan="10", port="Et0/0") for n in range(12)
    ]
    # The host of interest is learned on the uplink of swA and on the access port of swB.
    _collect(
        db,
        device="swA",
        macs=[*uplink_macs, ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Et0/0")],
    )
    _collect(
        db,
        device="swB",
        macs=[
            ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/5"),
            ClientMacRow(mac_address="aabb.ccdd.0002", vlan="10", port="Gi1/0/5"),
        ],
    )
    # Only seen on an uplink: no likely location.
    _collect(
        db,
        device="swC",
        macs=[
            ClientMacRow(mac_address=f"aabb.1111.{n:04x}", vlan="10", port="Po1") for n in range(11)
        ],
    )


def _row(items: list[dict], mac: str, device: str) -> dict:
    return _by_key(items)[(mac, device)]


def test_uplink_ports_and_the_likely_location_of_a_mac(db: Session) -> None:
    _uplink_lab(db)

    items, _ = ClientDataQueryRepository(db).get_client_data(mac_address="aabb.ccdd.0001")

    on_uplink = _row(items, "aabb.ccdd.0001", "swA")
    on_access = _row(items, "aabb.ccdd.0001", "swB")
    assert (on_uplink["macs_on_port"], on_uplink["is_uplink"]) == (13, True)
    assert (on_access["macs_on_port"], on_access["is_uplink"]) == (2, False)
    assert (on_uplink["likely_location"], on_access["likely_location"]) == (False, True)


def test_a_mac_seen_only_on_uplinks_has_no_likely_location(db: Session) -> None:
    _uplink_lab(db)

    items, _ = ClientDataQueryRepository(db).get_client_data(mac_address="aabb.1111.0000")

    (row,) = items
    assert (row["is_uplink"], row["likely_location"]) == (True, False)


def test_the_threshold_is_configurable(db: Session) -> None:
    _uplink_lab(db)

    items, _ = ClientDataQueryRepository(db, uplink_threshold=20).get_client_data(
        mac_address="aabb.ccdd.0001"
    )

    # Nothing counts as an uplink now; the port with the fewest MACs is still the likely one.
    assert not any(i["is_uplink"] for i in items)
    assert [i["device_name"] for i in items if i["likely_location"]] == ["swB"]


def test_ties_pick_one_likely_location_deterministically(db: Session) -> None:
    for device in ("swZ", "swB"):
        _collect(
            db,
            device=device,
            macs=[ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/1")],
        )

    items, _ = ClientDataQueryRepository(db).get_client_data()

    assert [(i["device_name"], i["likely_location"]) for i in items] == [
        ("swB", True),
        ("swZ", False),
    ]


def test_arp_only_rows_have_no_port_statistics(lab: Session) -> None:
    items, _ = ClientDataQueryRepository(lab).get_client_data(device_name="core1")

    assert all(
        (i["macs_on_port"], i["is_uplink"], i["likely_location"]) == (None, False, False)
        for i in items
    )


def test_hide_uplinks_leaves_access_ports_and_arp_rows(db: Session) -> None:
    _uplink_lab(db)

    items, total = ClientDataQueryRepository(db).get_client_data(hide_uplinks=True)

    assert total == len(items) == 2
    assert {i["device_name"] for i in items} == {"swB"}


def test_exact_matches_whole_values_in_any_notation_and_case(lab: Session) -> None:
    _collect(
        lab,
        device="core3",
        ips=[ClientIpRow(ip_address="10.0.10.50", mac_address="aabb.ccdd.0050")],
        hostnames=[ClientHostnameRow(ip_address="10.0.10.50", hostname="Host50.Example.net")],
    )
    repo = ClientDataQueryRepository(lab)

    assert {i["ip_address"] for i in repo.get_client_data(ip_address="10.0.10.5")[0]} == {
        "10.0.10.5",
        "10.0.10.50",
    }
    exact_ips = {
        i["ip_address"] for i in repo.get_client_data(ip_address="10.0.10.5", exact=True)[0]
    }
    assert exact_ips == {"10.0.10.5"}
    by_mac = repo.get_client_data(mac_address="AA:BB:CC:DD:00:50", exact=True)[0]
    assert [i["mac_address"] for i in by_mac] == ["aabb.ccdd.0050"]
    assert repo.get_client_data(mac_address="aabb.ccdd.005", exact=True)[0] == []
    by_host = repo.get_client_data(hostname="HOST50.example.NET", exact=True)[0]
    assert [i["ip_address"] for i in by_host] == ["10.0.10.50"]


def test_coverage_lists_each_devices_newest_collection(lab: Session) -> None:
    _collect(lab, device="acc1", session_id="run-2", at=NOW + timedelta(hours=1))

    coverage = ClientDataQueryRepository(lab).get_collections()

    assert [c["device_name"] for c in coverage] == ["acc1", "core1"]
    acc1 = coverage[0]
    assert (acc1["mac_rows"], acc1["arp_rows"]) == (0, 0)
    assert acc1["arp_status"] == "ok"
    assert acc1["collected_at"].startswith("2026-11-07T13:00")


def test_the_threshold_must_be_positive(db: Session) -> None:
    with pytest.raises(ValueError, match="uplink_threshold"):
        ClientDataQueryRepository(db, uplink_threshold=0)


@pytest.mark.parametrize(("macs", "is_uplink"), [(10, False), (11, True)])
def test_the_threshold_itself_is_not_yet_an_uplink(db: Session, macs: int, is_uplink: bool) -> None:
    _collect(
        db,
        device="sw",
        macs=[
            ClientMacRow(mac_address=f"aabb.0000.{n:04x}", vlan="10", port="Gi1/0/1")
            for n in range(macs)
        ],
    )

    items, _ = ClientDataQueryRepository(db).get_client_data(mac_address="aabb.0000.0000")

    assert items[0]["macs_on_port"] == macs
    assert items[0]["is_uplink"] is is_uplink


def test_an_arp_only_row_of_the_same_mac_does_not_take_the_likely_location(lab: Session) -> None:
    # In the lab, core1 has an ARP-only observation of the MAC that acc1 learned on Gi1/0/5.
    items, _ = ClientDataQueryRepository(lab).get_client_data(mac_address="aabb.ccdd.0001")

    by_device = {i["device_name"]: i for i in items}
    assert by_device["core1"]["likely_location"] is False
    assert by_device["acc1"]["likely_location"] is True


# --- "current" is per device AND per table -------------------------------------------------------

ARP_OFF = ClientCollectionStatus(arp_status="skipped", mac_status="ok", vrf_status="skipped")
MAC_OFF = ClientCollectionStatus(arp_status="ok", mac_status="skipped", vrf_status="ok")


def test_a_run_that_did_not_collect_a_table_keeps_the_earlier_rows_of_that_table(
    lab: Session,
) -> None:
    # core1 was collected with ARP in run-1. A later run only reads its MAC table (ARP off).
    _collect(
        lab,
        device="core1",
        session_id="run-2",
        at=NOW + timedelta(hours=1),
        macs=[ClientMacRow(mac_address="aabb.ccdd.0002", vlan="20", port="Gi0/9")],
        status=ARP_OFF,
    )

    items, _ = ClientDataQueryRepository(lab).get_client_data(device_name="core1")

    seen = {(i["mac_address"], i["port"], i["ip_address"]) for i in items}
    # The MAC-table row is new, the ARP rows of run-1 are still current.
    assert ("aabb.ccdd.0002", "Gi0/9", "10.0.20.7") in seen
    assert ("aabb.ccdd.0001", "Vlan10", "10.0.10.5") in seen


def test_a_run_that_did_not_collect_the_mac_table_keeps_the_earlier_mac_rows(lab: Session) -> None:
    _collect(
        lab,
        device="acc1",
        session_id="run-2",
        at=NOW + timedelta(hours=1),
        ips=[ClientIpRow(ip_address="10.0.10.77", mac_address="aabb.ccdd.0003", vlan="10")],
        status=MAC_OFF,
    )

    items, _ = ClientDataQueryRepository(lab).get_client_data(device_name="acc1")

    by_mac = {i["mac_address"]: i for i in items}
    assert by_mac["aabb.ccdd.0001"]["port"] == "Gi1/0/5"  # run-1's MAC table
    assert by_mac["aabb.ccdd.0003"]["port"] == "Gi1/0/6"
    assert by_mac["aabb.ccdd.0003"]["ip_address"] == "10.0.10.77"  # run-2's ARP


def test_a_table_the_device_now_refuses_replaces_the_earlier_rows(lab: Session) -> None:
    refused = ClientCollectionStatus(arp_status="ok", mac_status="not_supported")
    _collect(lab, device="acc1", session_id="run-2", at=NOW + timedelta(hours=1), status=refused)

    items, _ = ClientDataQueryRepository(lab).get_client_data(device_name="acc1")

    assert items == []  # "not_supported" is an observation, unlike "skipped"


def test_coverage_reports_each_table_with_the_time_it_was_last_collected(lab: Session) -> None:
    _collect(
        lab,
        device="core1",
        session_id="run-2",
        at=NOW + timedelta(hours=1),
        macs=[ClientMacRow(mac_address="aabb.ccdd.0002", vlan="20", port="Gi0/9")],
        status=ARP_OFF,
    )

    coverage = {c["device_name"]: c for c in ClientDataQueryRepository(lab).get_collections()}

    core1 = coverage["core1"]
    assert core1["arp_collected_at"].startswith("2026-11-07T12:00")
    assert core1["mac_collected_at"].startswith("2026-11-07T13:00")
    assert core1["collected_at"].startswith("2026-11-07T13:00")
    assert (core1["arp_rows"], core1["mac_rows"]) == (2, 1)
    assert (core1["arp_status"], core1["mac_status"]) == ("ok", "ok")


def test_a_table_never_collected_is_reported_as_skipped(db: Session) -> None:
    _collect(
        db,
        device="sw",
        macs=[ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/1")],
        status=ARP_OFF,
    )

    (sw,) = ClientDataQueryRepository(db).get_collections()

    assert (sw["arp_status"], sw["arp_collected_at"], sw["arp_rows"]) == ("skipped", None, 0)
    assert sw["mac_rows"] == 1


def test_hostnames_follow_the_arp_collection(lab: Session) -> None:
    # core1's hostname was collected with its ARP table in run-1; a later MAC-only run keeps it.
    _collect(
        lab,
        device="core1",
        session_id="run-2",
        at=NOW + timedelta(hours=1),
        macs=[ClientMacRow(mac_address="aabb.ccdd.0002", vlan="20", port="Gi0/9")],
        status=ARP_OFF,
    )

    items, _ = ClientDataQueryRepository(lab).get_client_data(ip_address="10.0.10.5", exact=True)

    assert {i["hostname"] for i in items} == {"pc1.example.net"}


def test_coverage_takes_vrf_information_from_the_arp_collection(db: Session) -> None:
    with_vrfs = ClientCollectionStatus(
        arp_status="ok", mac_status="skipped", vrf_status="ok", vrf_count=2
    )
    _collect(
        db,
        device="core",
        session_id="arp-run",
        ips=[ClientIpRow(ip_address="10.0.0.1", mac_address="aabb.ccdd.0001", vrf="CUST")],
        status=with_vrfs,
    )
    _collect(
        db,
        device="core",
        session_id="mac-run",
        at=NOW + timedelta(hours=1),
        macs=[ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi0/1")],
        status=ARP_OFF,
    )

    (core,) = ClientDataQueryRepository(db).get_collections()

    assert (core["vrf_status"], core["vrf_count"]) == ("ok", 2)


# --- review findings: ordering before LIMIT, history collapse, IPv6, prefix, ages, ties ----------


def test_likely_first_puts_the_access_port_on_the_first_page_of_a_large_result(db: Session) -> None:
    for n in range(60):  # 60 switches see the MAC on an uplink (a second MAC makes it one)
        _collect(
            db,
            device=f"sw{n:02d}",
            macs=[
                ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Et0/0"),
                ClientMacRow(mac_address=f"aabb.0000.{n:04x}", vlan="10", port="Et0/0"),
            ],
        )
    _collect(
        db,
        device="zzz-access",  # sorts after every switch above
        macs=[ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/5")],
    )
    repo = ClientDataQueryRepository(db, uplink_threshold=1)

    plain, total = repo.get_client_data(mac_address="aabb.ccdd.0001", exact=True, page_size=5)
    first, total_first = repo.get_client_data(
        mac_address="aabb.ccdd.0001", exact=True, page_size=5, likely_first=True
    )

    assert total == total_first == 61
    assert not any(r["likely_location"] for r in plain)  # the default order hides it
    assert first[0]["device_name"] == "zzz-access"
    assert first[0]["likely_location"] is True
    assert [r["is_uplink"] for r in first[1:]] == [True] * 4


def test_history_collapses_before_the_limit_so_older_collections_are_not_lost(db: Session) -> None:
    for session in range(3):  # three collections; the MAC is in three VLANs of each
        _collect(
            db,
            device="h",
            session_id=f"s{session}",
            at=NOW + timedelta(hours=session),
            ips=[ClientIpRow(ip_address="10.0.0.5", mac_address="aabb.ccdd.0005")],
            macs=[
                ClientMacRow(mac_address="aabb.ccdd.0005", vlan=vlan, port="Gi0/1")
                for vlan in ("10", "20", "30")
            ],
        )

    history = ClientDataQueryRepository(db).get_client_history(ip_address="10.0.0.5", limit=4)

    assert len(history["ip_history"]) == 3  # one per collection, not 4 of the 9 joined rows
    assert [h["collected_at"][:13] for h in history["ip_history"]] == [
        "2026-11-07T14",
        "2026-11-07T13",
        "2026-11-07T12",
    ]


def test_history_limit_counts_collapsed_entries(db: Session) -> None:
    for session in range(4):
        _collect(
            db,
            device="h",
            session_id=f"s{session}",
            at=NOW + timedelta(hours=session),
            macs=[ClientMacRow(mac_address="aabb.ccdd.0005", vlan="10", port="Gi0/1")],
        )

    history = ClientDataQueryRepository(db).get_client_history(
        mac_address="aabb.ccdd.0005", limit=2
    )

    assert [h["collected_at"][:13] for h in history["mac_history"]] == [
        "2026-11-07T15",
        "2026-11-07T14",
    ]


@pytest.mark.parametrize(
    "typed",
    ["2001:db8::5", "2001:DB8::5", "2001:0db8:0000:0000:0000:0000:0000:0005", " 2001:db8::5 "],
)
def test_an_ipv6_address_is_matched_in_any_notation(db: Session, typed: str) -> None:
    _collect(
        db, device="v6", ips=[ClientIpRow(ip_address="2001:db8::5", mac_address="aabb.ccdd.0006")]
    )
    repo = ClientDataQueryRepository(db)

    assert repo.get_client_data(ip_address=typed, exact=True)[1] == 1
    assert len(repo.get_client_history(ip_address=typed)["ip_history"]) == 1


def test_ip_prefix_matches_the_start_of_the_address_only(db: Session) -> None:
    _collect(
        db,
        device="p",
        ips=[
            ClientIpRow(ip_address="110.1.2.3", mac_address="aabb.ccdd.0007"),
            ClientIpRow(ip_address="10.1.2.3", mac_address="aabb.ccdd.0008"),
            ClientIpRow(ip_address="10.10.2.3", mac_address="aabb.ccdd.0009"),
        ],
    )
    repo = ClientDataQueryRepository(db)

    items, _ = repo.get_client_data(ip_prefix="10.1.")

    assert [i["ip_address"] for i in items] == ["10.1.2.3"]  # not 110.1.2.3, not 10.10.2.3


def test_a_mac_table_row_carries_the_time_of_the_arp_collection_that_gave_its_ip(
    lab: Session,
) -> None:
    # acc1's MAC table is re-read an hour later; the IP of the MAC still comes from core1's ARP.
    _collect(
        lab,
        device="acc1",
        session_id="run-2",
        at=NOW + timedelta(hours=1),
        macs=[ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/5")],
        status=ClientCollectionStatus(arp_status="skipped", mac_status="ok"),
    )

    items, _ = ClientDataQueryRepository(lab).get_client_data(mac_address="aabb.ccdd.0001")

    by_device = {i["device_name"]: i for i in items}
    acc1 = by_device["acc1"]
    assert acc1["collected_at"].startswith("2026-11-07T13:00")  # the port: run-2
    assert acc1["ip_address"] == "10.0.10.5"
    assert acc1["ip_collected_at"].startswith("2026-11-07T12:00")  # the IP: core1's ARP, run-1
    core1 = by_device["core1"]
    assert core1["ip_collected_at"] == core1["collected_at"]  # an ARP-only row: one time


def test_a_row_without_an_ip_has_no_ip_time(lab: Session) -> None:
    items, _ = ClientDataQueryRepository(lab).get_client_data(mac_address="aabb.ccdd.0003")

    (row,) = items
    assert (row["ip_address"], row["ip_collected_at"]) == (None, None)


@pytest.mark.parametrize("order", [("10", "20"), ("20", "10")])
def test_equal_scores_pick_the_same_likely_location_whatever_the_insertion_order(
    db: Session, order: tuple[str, str]
) -> None:
    _collect(
        db,
        device="t",
        macs=[ClientMacRow(mac_address="aabb.ccdd.0009", vlan=v, port="Gi1") for v in order],
    )

    items, _ = ClientDataQueryRepository(db).get_client_data(mac_address="aabb.ccdd.0009")

    assert {r["vlan"]: r["likely_location"] for r in items} == {"10": True, "20": False}


def test_the_ip_time_is_that_of_the_same_devices_arp_when_the_mac_table_is_newer(
    db: Session,
) -> None:
    _collect(
        db,
        device="l3sw",
        session_id="arp-run",
        ips=[ClientIpRow(ip_address="10.0.0.5", mac_address="aabb.ccdd.0001", vlan="10")],
        macs=[ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/1")],
    )
    _collect(
        db,
        device="l3sw",
        session_id="mac-run",
        at=NOW + timedelta(hours=2),
        macs=[ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/2")],
        status=ClientCollectionStatus(arp_status="skipped", mac_status="ok"),
    )

    items, _ = ClientDataQueryRepository(db).get_client_data(mac_address="aabb.ccdd.0001")

    mac_row = next(i for i in items if i["port"] == "Gi1/0/2")
    assert mac_row["ip_address"] == "10.0.0.5"  # the same device's ARP
    assert mac_row["collected_at"].startswith("2026-11-07T14:00")  # the new MAC table
    assert mac_row["ip_collected_at"].startswith("2026-11-07T12:00")  # the older ARP

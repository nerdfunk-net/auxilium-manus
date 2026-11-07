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
) -> None:
    ClientDataRepository(db).replace_device_collection(
        session_id=session_id,
        device_name=device,
        device_ip=None,
        collected_at=at,
        ip_rows=ips or [],
        mac_rows=macs or [],
        hostname_rows=hostnames or [],
        status=OK,
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

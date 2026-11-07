"""Client data tables on real Postgres.

The unit tests run the same queries on SQLite; this proves them on the production dialect
(window functions, ``ILIKE ... ESCAPE``, ``UNION`` CTEs, ``NULLS LAST``, tuple ``IN``) and the
unique collection constraint. Uses ``clean_tables`` because the repositories commit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

import core.database as db_mod
from core.models.client_data import ClientDataCollection, ClientIpAddress, ClientMacAddress
from models.client_data import (
    ClientCollectionStatus,
    ClientHostnameRow,
    ClientIpRow,
    ClientMacRow,
)
from repositories.client_data_query_repository import ClientDataQueryRepository
from repositories.client_data_repository import ClientDataRepository

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("require_postgres", "clean_tables"),
]

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
OK = ClientCollectionStatus(arp_status="ok", mac_status="ok", vrf_status="ok")


@pytest.fixture
def session():
    s = db_mod.SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _collect(session, *, device, session_id="run-1", at=NOW, ips=(), macs=(), hostnames=()):
    ClientDataRepository(session).replace_device_collection(
        session_id=session_id,
        device_name=device,
        device_ip=None,
        collected_at=at,
        ip_rows=list(ips),
        mac_rows=list(macs),
        hostname_rows=list(hostnames),
        status=OK,
        keep_sessions=5,
    )


@pytest.fixture
def lab(session):
    _collect(
        session,
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
        session,
        device="acc1",
        macs=[
            ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/5"),
            ClientMacRow(mac_address="aabb.ccdd.0003", vlan="10", port="Gi1/0/6"),
        ],
    )
    return session


def _by_key(items):
    return {(i["mac_address"], i["device_name"]): i for i in items}


def test_correlation_across_devices(lab) -> None:
    items, total = ClientDataQueryRepository(lab).get_client_data()

    assert total == 4
    rows = _by_key(items)
    l2 = rows[("aabb.ccdd.0001", "acc1")]
    assert (l2["port"], l2["vlan"], l2["ip_address"], l2["hostname"]) == (
        "Gi1/0/5",
        "10",
        "10.0.10.5",
        "pc1.example.net",
    )
    assert rows[("aabb.ccdd.0002", "core1")]["vrf"] == "CUST"
    assert rows[("aabb.ccdd.0003", "acc1")]["ip_address"] is None
    assert items[-1]["ip_address"] is None  # NULLS LAST ordering by IP
    assert isinstance(items[0]["collected_at"], str)


def test_latest_is_per_device_and_an_empty_collection_hides_old_rows(lab) -> None:
    _collect(lab, device="acc1", session_id="run-2", at=NOW + timedelta(hours=1))

    repo = ClientDataQueryRepository(lab)
    assert repo.get_client_data(device_name="acc1")[0] == []
    assert ("aabb.ccdd.0002", "core1") in _by_key(repo.get_client_data()[0])


def test_ilike_wildcards_are_literal_and_filters_are_case_insensitive(lab) -> None:
    repo = ClientDataQueryRepository(lab)

    assert repo.get_client_data(mac_address="%") == ([], 0)
    assert repo.get_client_data(mac_address="_")[1] == 0
    assert {i["mac_address"] for i in repo.get_client_data(hostname="PC1")[0]} == {"aabb.ccdd.0001"}
    assert repo.get_client_data(vrf="cust")[1] == 1


def test_history_and_device_names(lab) -> None:
    _collect(
        lab,
        device="acc1",
        session_id="run-2",
        at=NOW + timedelta(hours=1),
        macs=[ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/9")],
    )

    repo = ClientDataQueryRepository(lab)
    history = repo.get_client_history(mac_address="aabb.ccdd.0001", ip_address="10.0.10.5")
    assert [r["port"] for r in history["mac_history"]] == ["Gi1/0/9", "Gi1/0/5"]
    assert history["ip_history"][0]["device_name"] == "core1"
    assert repo.get_device_names() == ["acc1", "core1"]


def test_purge_keeps_each_devices_newest_collection(lab) -> None:
    repo = ClientDataRepository(lab)
    for index in range(1, 4):
        _collect(
            lab,
            device="acc1",
            session_id=f"s{index}",
            at=NOW - timedelta(days=200 - index),
            macs=[ClientMacRow(mac_address="aabb.ccdd.0009", port="Gi1/0/1")],
        )

    deleted = repo.purge_older_than(NOW - timedelta(days=90), batch_size=1)

    assert deleted > 0
    remaining = set(
        lab.execute(select(ClientDataCollection.device_name, ClientDataCollection.session_id)).all()
    )
    # Only each device's newest collection is left: acc1's run-1 (at NOW) and core1's run-1.
    assert remaining == {("acc1", "run-1"), ("core1", "run-1")}
    assert lab.scalar(select(func.count()).select_from(ClientMacAddress)) == 2
    assert lab.scalar(select(func.count()).select_from(ClientIpAddress)) == 2


def test_arp_without_a_vlan_does_not_multiply_mac_rows_and_other_vlan_ips_are_not_borrowed(
    session,
) -> None:
    _collect(
        session,
        device="sw",
        macs=[
            ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/1"),
            ClientMacRow(mac_address="aabb.ccdd.0001", vlan="20", port="Gi1/0/2"),
            ClientMacRow(mac_address="aabb.ccdd.0009", vlan="10", port="Gi1/0/9"),
        ],
        ips=[
            ClientIpRow(ip_address="10.1.1.1", mac_address="aabb.ccdd.0001", interface="Gi0/1"),
            ClientIpRow(ip_address="10.1.1.2", mac_address="aabb.ccdd.0001", interface="Gi0/1"),
        ],
    )
    _collect(
        session,
        device="core",
        ips=[ClientIpRow(ip_address="10.9.9.9", mac_address="aabb.ccdd.0009", vlan="99")],
    )

    items, total = ClientDataQueryRepository(session).get_client_data(device_name="sw")

    assert total == len(items) == 5  # 3 MAC observations + 2 ARP observations, not a product
    nine = [i for i in items if i["mac_address"] == "aabb.ccdd.0009"]
    assert [(i["vlan"], i["ip_address"]) for i in nine] == [("10", None)]

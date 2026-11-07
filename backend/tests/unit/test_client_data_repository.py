"""Write path and retention of ClientDataRepository (SQLite; reads need PostgreSQL)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import Table, create_engine, func, select
from sqlalchemy.exc import OperationalError
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
from repositories.client_data_repository import ClientDataRepository

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
TABLES = [
    cast("Table", model.__table__)
    for model in (ClientIpAddress, ClientMacAddress, ClientHostname, ClientDataCollection)
]


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=TABLES)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


def _count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def _store(
    repo: ClientDataRepository,
    *,
    session_id: str = "s1",
    device: str = "sw1",
    at: datetime = NOW,
    ips: int = 1,
    macs: int = 1,
    keep: int = 5,
) -> None:
    repo.replace_device_collection(
        session_id=session_id,
        device_name=device,
        device_ip="192.0.2.1",
        collected_at=at,
        ip_rows=[
            ClientIpRow(ip_address=f"10.0.0.{i + 1}", mac_address="aabb.ccdd.eeff", vlan="10")
            for i in range(ips)
        ],
        mac_rows=[
            ClientMacRow(mac_address=f"aabb.ccdd.{i:04x}", vlan="10", port="Gi1/0/1")
            for i in range(macs)
        ],
        hostname_rows=[ClientHostnameRow(ip_address="10.0.0.1", hostname="host.example.net")],
        status=ClientCollectionStatus(arp_status="ok", mac_status="ok", vrf_status="ok"),
        keep_sessions=keep,
    )


def test_replace_stores_rows_and_collection(db: Session) -> None:
    _store(ClientDataRepository(db), ips=2, macs=3)

    assert _count(db, ClientIpAddress) == 2
    assert _count(db, ClientMacAddress) == 3
    assert _count(db, ClientHostname) == 1
    collection = db.scalars(select(ClientDataCollection)).one()
    assert (collection.session_id, collection.device_name) == ("s1", "sw1")
    assert (collection.arp_rows, collection.mac_rows) == (2, 3)
    assert collection.mac_status == "ok"
    stored = db.scalars(select(ClientIpAddress)).first()
    assert stored is not None
    assert (stored.device_ip, stored.vlan) == ("192.0.2.1", "10")


def test_same_session_and_device_is_replaced_not_duplicated(db: Session) -> None:
    repo = ClientDataRepository(db)
    _store(repo, ips=3, macs=3)
    _store(repo, ips=1, macs=1)

    assert _count(db, ClientIpAddress) == 1
    assert _count(db, ClientMacAddress) == 1
    assert _count(db, ClientDataCollection) == 1


def test_other_devices_of_the_same_session_are_untouched(db: Session) -> None:
    repo = ClientDataRepository(db)
    _store(repo, device="sw1")
    _store(repo, device="sw2")
    _store(repo, device="sw1", ips=2)

    assert _count(db, ClientDataCollection) == 2
    names = set(db.scalars(select(ClientIpAddress.device_name)))
    assert names == {"sw1", "sw2"}


def test_empty_collection_is_recorded(db: Session) -> None:
    repo = ClientDataRepository(db)
    repo.replace_device_collection(
        session_id="s1",
        device_name="core1",
        device_ip=None,
        collected_at=NOW,
        ip_rows=[],
        mac_rows=[],
        hostname_rows=[],
        status=ClientCollectionStatus(arp_status="ok", mac_status="not_supported"),
        keep_sessions=5,
    )

    assert _count(db, ClientIpAddress) == 0
    collection = db.scalars(select(ClientDataCollection)).one()
    assert (collection.arp_status, collection.mac_status) == ("ok", "not_supported")
    assert (collection.arp_rows, collection.mac_rows) == (0, 0)


def test_keeps_only_the_newest_sessions_per_device(db: Session) -> None:
    repo = ClientDataRepository(db)
    for index in range(1, 4):
        _store(repo, session_id=f"s{index}", at=NOW + timedelta(hours=index), keep=2)
    _store(repo, session_id="s1", device="sw2", at=NOW, keep=2)

    sw1_sessions = set(
        db.scalars(
            select(ClientDataCollection.session_id).where(ClientDataCollection.device_name == "sw1")
        )
    )
    assert sw1_sessions == {"s2", "s3"}
    assert set(
        db.scalars(select(ClientIpAddress.session_id).where(ClientIpAddress.device_name == "sw1"))
    ) == {"s2", "s3"}
    assert set(
        db.scalars(select(ClientMacAddress.session_id).where(ClientMacAddress.device_name == "sw1"))
    ) == {"s2", "s3"}
    # sw2 has a single session and is not affected by sw1's pruning.
    assert _count(db, ClientDataCollection) == 3


def test_purge_removes_old_collections_but_keeps_each_devices_newest(db: Session) -> None:
    repo = ClientDataRepository(db)
    old = NOW - timedelta(days=200)
    _store(repo, session_id="s1", device="sw1", at=old)
    _store(repo, session_id="s2", device="sw1", at=old + timedelta(days=1))
    _store(repo, session_id="s1", device="gone", at=old)  # only collection, long ago

    deleted = repo.purge_older_than(NOW - timedelta(days=90), batch_size=1)

    assert deleted > 0
    remaining = set(
        db.execute(select(ClientDataCollection.device_name, ClientDataCollection.session_id))
    )
    assert remaining == {("sw1", "s2"), ("gone", "s1")}
    assert set(db.scalars(select(ClientIpAddress.session_id))) == {"s2", "s1"}


def test_purge_keeps_collections_newer_than_the_cutoff(db: Session) -> None:
    repo = ClientDataRepository(db)
    _store(repo, session_id="s1", at=NOW - timedelta(days=10))
    _store(repo, session_id="s2", at=NOW - timedelta(days=5))

    assert repo.purge_older_than(NOW - timedelta(days=90)) == 0
    assert _count(db, ClientDataCollection) == 2


def test_failed_commit_rolls_back_and_keeps_the_earlier_collection(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = ClientDataRepository(db)
    _store(repo, ips=2)

    def _boom() -> None:
        raise OperationalError("COMMIT", {}, Exception("disk full"))

    monkeypatch.setattr(db, "commit", _boom)
    with pytest.raises(OperationalError):
        _store(repo, ips=1)
    monkeypatch.undo()

    assert _count(db, ClientIpAddress) == 2
    assert _count(db, ClientDataCollection) == 1


def test_keep_sessions_below_one_is_rejected(db: Session) -> None:
    with pytest.raises(ValueError, match="keep_sessions"):
        _store(ClientDataRepository(db), keep=0)


def test_a_collection_older_than_the_kept_ones_is_not_pruned_away_in_the_same_write(
    db: Session,
) -> None:
    # An overlapping run finished first; this run started earlier but is written last.
    repo = ClientDataRepository(db)
    for index in range(1, 6):
        _store(repo, session_id=f"s{index}", at=NOW + timedelta(hours=index), keep=5)

    _store(repo, session_id="early", at=NOW, keep=5)

    sessions = set(db.scalars(select(ClientDataCollection.session_id)))
    assert "early" in sessions
    assert _count(db, ClientIpAddress) == len(sessions)  # its rows are there too

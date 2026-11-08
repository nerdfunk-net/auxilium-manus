"""The tools over the real repository (SQLite): what the stubbed-reader tests cannot show."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from sqlalchemy.orm import Session

from models.client_data import ClientCollectionStatus, ClientMacRow, ClientNeighborRow
from repositories.client_data_query_repository import ClientDataQueryRepository
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.tools.base import Toolbox, ToolContext
from services.ai_assistant.tools.client_data_tools import (
    CLIENT_DATA_READER_KEY,
    build_client_data_tools,
)
from tests.unit.test_client_data_query_repository import _collect, db  # noqa: F401


class RepositoryReader:
    """The reader contract over a real repository (no permission check; that is its own test)."""

    def __init__(self, session: Session, threshold: int) -> None:
        self._repo = ClientDataQueryRepository(session, uplink_threshold=threshold)

    async def observations(self, **filters: Any):
        return self._repo.get_client_data(**filters)

    async def history(self, **filters: Any):
        return self._repo.get_client_history(**filters)

    async def coverage(self):
        return self._repo.get_collections()


def _run(reader: Any, name: str, **args: Any) -> dict[str, Any]:
    ctx = ToolContext(
        user_id=1,
        redactor=Redactor(),
        extras={CLIENT_DATA_READER_KEY: reader},
        sharing=SharingPolicy(inventory=True, addresses=True),
    )
    out = asyncio.run(Toolbox(build_client_data_tools(), ctx).execute(ToolCall("1", name, args)))
    assert not out.is_error, out.content
    return json.loads(out.content)


@pytest.fixture
def large_l2_domain(db: Session) -> Session:  # noqa: F811
    for n in range(60):  # 60 switches learn the host on an uplink
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
        device="zzz-access",
        macs=[ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/5")],
    )
    return db


def test_find_client_names_the_access_port_in_a_domain_of_sixty_one_switches(
    large_l2_domain: Session,
) -> None:
    data = _run(
        RepositoryReader(large_l2_domain, threshold=1), "find_client", address="aabb.ccdd.0001"
    )

    assert data["likely_location"]["device"] == "zzz-access"
    assert data["likely_location"]["port"] == "Gi1/0/5"
    assert data["rows"][0]["device"] == "zzz-access"
    assert data["total_rows"] == 61
    assert "no access port" not in data["note"].lower()


def test_find_client_uses_the_lldp_neighbour_to_find_the_access_port_through_the_real_query(
    db: Session,  # noqa: F811
) -> None:
    status = ClientCollectionStatus(arp_status="ok", mac_status="ok", neighbor_status="ok")
    # swA sees the host on a trunk with ONE other MAC (the count rule would call it an access
    # port and, having fewer MACs, prefer it); its LLDP neighbour is a router.
    _collect(
        db,
        device="swA",
        macs=[
            ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/48"),
            ClientMacRow(mac_address="aabb.0000.0002", vlan="10", port="Gi1/0/48"),
        ],
        neighbors=[
            ClientNeighborRow(
                port="Gi1/0/48",
                neighbor_name="core1",
                protocol="lldp",
                capabilities="bridge,router",
                is_infrastructure=True,
            )
        ],
        status=status,
    )
    _collect(
        db,
        device="swB",
        macs=[
            ClientMacRow(mac_address="aabb.ccdd.0001", vlan="10", port="Gi1/0/5"),
            ClientMacRow(mac_address="aabb.0000.0003", vlan="10", port="Gi1/0/5"),
            ClientMacRow(mac_address="aabb.0000.0004", vlan="10", port="Gi1/0/5"),
        ],
    )

    data = _run(RepositoryReader(db, threshold=10), "find_client", address="aabb.ccdd.0001")

    assert data["likely_location"]["device"] == "swB"
    by_device = {r["device"]: r for r in data["rows"]}
    assert (by_device["swA"]["is_uplink"], by_device["swA"]["uplink_reason"]) == (True, "neighbor")
    assert by_device["swA"]["uplink_to"] == "core1"

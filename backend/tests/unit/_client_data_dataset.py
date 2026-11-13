"""A seeded, deliberately awkward client-data dataset.

Shared by the SQLite unit test and the PostgreSQL integration test that prove the narrowed lookup
returns exactly what the full view returns. It has what the correlation has to cope with: a MAC
seen by several devices, a MAC with several IPs, one IP on several MACs, ARP rows with and without
VLAN / VRF / MAC, IPv6, MAC-table rows without VLAN, busy ports (uplinks by count), LLDP
neighbours (uplinks by neighbour, through a port-channel), a device whose newest collection is
empty and a device with an older, replaced collection.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from models.client_data import (
    ClientCollectionStatus,
    ClientHostnameRow,
    ClientIpRow,
    ClientMacRow,
    ClientNeighborRow,
)

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
_SWITCH = ClientCollectionStatus(
    arp_status="skipped", mac_status="ok", vrf_status="skipped", neighbor_status="ok"
)
_ROUTER = ClientCollectionStatus(arp_status="ok", mac_status="skipped", vrf_status="ok")
_VLANS = ("10", "20", None)
_PORTS = ("Gi1/0/1", "Gi1/0/2", "Gi1/0/3", "Gi1/0/4", "Po1")

Collect = Callable[..., None]


@dataclass(frozen=True)
class Facts:
    """Values that exist in the dataset, to build lookups from."""

    ip: str  # an IPv4 address with a MAC and a hostname
    ipv6: str
    mac: str  # a MAC seen by a switch and in an ARP table
    switch: str
    router: str
    port: str
    hostname: str


def build_dataset(collect: Collect, session: Any, seed: int = 7) -> Facts:
    """Write the dataset with *collect* (the test module's ``_collect``) and describe it."""
    rng = random.Random(seed)  # noqa: S311 - a reproducible shape, not a secret
    macs = [f"aabb.ccdd.{n:04x}" for n in range(48)]
    ips = [f"10.{n % 3}.{n % 5}.{n + 1}" for n in range(60)] + [f"2001:db8::{n:x}" for n in (1, 2)]

    def mac_rows(count: int, *, pool: list[str]) -> list[ClientMacRow]:
        return [
            ClientMacRow(
                mac_address=rng.choice(pool), vlan=rng.choice(_VLANS), port=rng.choice(_PORTS)
            )
            for _ in range(count)
        ]

    def arp_rows(count: int) -> list[ClientIpRow]:
        rows = []
        for _ in range(count):
            vlan = rng.choice(_VLANS)
            rows.append(
                ClientIpRow(
                    ip_address=rng.choice(ips),
                    mac_address=None if rng.random() < 0.1 else rng.choice(macs),
                    interface=f"Vlan{vlan}" if vlan else "Gi0/0",
                    vrf=rng.choice((None, None, "CUST")),
                    vlan=vlan,
                )
            )
        return rows

    neighbours = {
        "sw1": [
            ClientNeighborRow(
                port="Gi1/0/1",
                neighbor_name="core-a",
                protocol="lldp",
                capabilities="bridge",
                is_infrastructure=True,
            )
        ],
        "sw2": [
            ClientNeighborRow(
                port="Gi1/0/3",
                neighbor_name="phone",
                protocol="cdp",
                capabilities="station",
                is_infrastructure=False,
            )
        ],
        "sw3": [
            ClientNeighborRow(
                port="Gi1/0/2",
                channel="Po1",
                neighbor_name="core-b",
                protocol="lldp",
                capabilities="router",
                is_infrastructure=True,
            )
        ],
    }
    # A switch with an older collection that the next one replaces.
    collect(
        session,
        device="sw4",
        session_id="run-0",
        at=NOW - timedelta(hours=1),
        macs=mac_rows(8, pool=macs),
        status=_SWITCH,
    )
    for index in range(1, 7):
        name = f"sw{index}"
        collect(
            session,
            device=name,
            macs=mac_rows(14, pool=macs),
            neighbors=neighbours.get(name, []),
            status=_SWITCH,
        )
    # The newest collection of sw6 found nothing: it hides the older rows.
    collect(
        session,
        device="sw6",
        session_id="run-2",
        at=NOW + timedelta(hours=1),
        status=_SWITCH,
    )
    shown_ip = "10.0.0.1"
    for index in range(1, 4):
        rows = arp_rows(20)
        if index == 1:
            rows.append(
                ClientIpRow(
                    ip_address=shown_ip,
                    mac_address=macs[0],
                    interface="Vlan10",
                    vlan="10",
                )
            )
            # The same address and MAC in a customer VRF: one more observation of the host.
            rows.append(
                ClientIpRow(
                    ip_address=shown_ip,
                    mac_address=macs[0],
                    interface="Vlan10",
                    vrf="CUST",
                    vlan="10",
                )
            )
        if index == 2:
            rows.append(
                ClientIpRow(
                    ip_address="2001:db8::1", mac_address=macs[1], interface="Vlan20", vlan="20"
                )
            )
        collect(
            session,
            device=f"rt{index}",
            ips=rows,
            hostnames=(
                [ClientHostnameRow(ip_address=shown_ip, hostname="host-one.example.net")]
                if index == 1
                else []
            ),
            status=_ROUTER,
        )
    # The host of interest sits on a switch port and in an ARP table.
    collect(
        session,
        device="sw1",
        session_id="run-3",
        at=NOW + timedelta(minutes=5),
        macs=[ClientMacRow(mac_address=macs[0], vlan="10", port="Gi1/0/4")],
        neighbors=neighbours["sw1"],
        status=_SWITCH,
    )
    return Facts(
        ip=shown_ip,
        ipv6="2001:db8::1",
        mac=macs[0],
        switch="sw1",
        router="rt1",
        port="Gi1/0/4",
        hostname="host-one.example.net",
    )

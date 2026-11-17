"""Mapping of Catalyst Center clients to client data rows."""

from __future__ import annotations

from models.catalyst_center_facts import CatalystCenterClient
from workflow_steps.get_catalyst_center_client_data.mapping import map_clients


def _client(mac: str | None, *ips: str, vlan: str | None = "10", port: str | None = "Gi1/0/3"):
    return CatalystCenterClient(mac_address=mac, ip_addresses=ips, vlan=vlan, port=port)


def test_client_becomes_a_mac_row_and_one_ip_row_per_address() -> None:
    ip_rows, mac_rows = map_clients([_client("AA:BB:CC:DD:EE:01", "10.0.0.5", "fe80::1")])
    assert [(r.mac_address, r.vlan, r.port) for r in mac_rows] == [
        ("aabb.ccdd.ee01", "10", "Gi1/0/3")
    ]
    assert [(r.ip_address, r.mac_address, r.vlan, r.vrf, r.interface) for r in ip_rows] == [
        ("10.0.0.5", "aabb.ccdd.ee01", "10", None, None),
        ("fe80::1", "aabb.ccdd.ee01", "10", None, None),
    ]


def test_client_without_ip_only_has_a_mac_row() -> None:
    ip_rows, mac_rows = map_clients([_client("aabb.ccdd.ee01")])
    assert ip_rows == ()
    assert len(mac_rows) == 1


def test_client_without_a_usable_mac_is_skipped() -> None:
    assert map_clients([_client(None, "10.0.0.5"), _client("garbage", "10.0.0.6")]) == ((), ())


def test_duplicates_collapse() -> None:
    first = _client("aa:bb:cc:dd:ee:01", "10.0.0.5")
    ip_rows, mac_rows = map_clients([first, first, _client("AABB.CCDD.EE01", "10.0.0.5")])
    assert len(ip_rows) == 1
    assert len(mac_rows) == 1


def test_same_mac_on_two_ports_keeps_both() -> None:
    _, mac_rows = map_clients(
        [_client("aa:bb:cc:dd:ee:01", port="Gi1/0/3"), _client("aa:bb:cc:dd:ee:01", port="Gi1/0/4")]
    )
    assert len(mac_rows) == 2


def test_port_is_shortened_like_the_mac_table() -> None:
    _, mac_rows = map_clients([_client("aa:bb:cc:dd:ee:01", port="GigabitEthernet2/1/3")])
    assert mac_rows[0].port == "Gi2/1/3"
    _, nxos = map_clients([_client("aa:bb:cc:dd:ee:01", port="Ethernet1/5")], platform="NX-OS")
    assert nxos[0].port == "Eth1/5"


def test_missing_port_stays_empty() -> None:
    _, mac_rows = map_clients([_client("aa:bb:cc:dd:ee:01", port=None)])
    assert mac_rows[0].port is None

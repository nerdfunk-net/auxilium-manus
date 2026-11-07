"""Rows are fitted to their column widths so one overlong value cannot drop a collection."""

from __future__ import annotations

from models.client_data import ClientHostnameRow, ClientIpRow, ClientMacRow


def test_overlong_values_are_truncated_to_the_column_width() -> None:
    ip = ClientIpRow(ip_address="10.0.0.1", interface="I" * 300, vrf="V" * 100, vlan="9" * 40)
    mac = ClientMacRow(mac_address="aabb.ccdd.eeff", vlan="9" * 40, port="P" * 300)
    host = ClientHostnameRow(ip_address="10.0.0.1", hostname="h" * 300)

    assert (len(ip.interface or ""), len(ip.vrf or ""), len(ip.vlan or "")) == (255, 64, 20)
    assert (len(mac.vlan or ""), len(mac.port or "")) == (20, 255)
    assert len(host.hostname) == 255


def test_values_within_the_width_are_unchanged() -> None:
    row = ClientIpRow(ip_address="10.0.0.1", interface="Vlan10", vrf="CUST", vlan="10")

    assert (row.interface, row.vrf, row.vlan) == ("Vlan10", "CUST", "10")

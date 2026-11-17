"""Map Catalyst Center clients to client data rows (pure, no I/O)."""

from __future__ import annotations

from collections.abc import Iterable

from models.catalyst_center_facts import CatalystCenterClient
from models.client_data import ClientIpRow, ClientMacRow
from workflow_steps.common.mac_address import normalise_mac
from workflow_steps.common.port_names import normalise_port


def map_clients(
    clients: Iterable[CatalystCenterClient], *, platform: str = ""
) -> tuple[tuple[ClientIpRow, ...], tuple[ClientMacRow, ...]]:
    """Return ``(ip_rows, mac_rows)`` for the clients of one switch.

    A client with a usable MAC address becomes one MAC row (MAC, VLAN, port) and one IP row per
    reported address. A client without a MAC is skipped: neither table can hold it. The
    port is shortened the way the MAC address table prints it (``GigabitEthernet2/1/3`` ->
    ``Gi2/1/3``), so port filters and uplink matching see the same name as for SSH data. The
    controller does not report the VRF or the layer-3 interface of an address, so both stay empty.
    Duplicates (a client listed twice) collapse to one row.
    """
    ip_rows: dict[tuple[str, str, str | None], ClientIpRow] = {}
    mac_rows: dict[tuple[str, str | None, str | None], ClientMacRow] = {}
    for client in clients:
        mac = normalise_mac(client.mac_address)
        if mac is None:
            continue
        mac_row = ClientMacRow(
            mac_address=mac,
            vlan=client.vlan,
            port=normalise_port(client.port, platform.lower().replace("-", "")) or None,
        )
        mac_rows.setdefault((mac, mac_row.vlan, mac_row.port), mac_row)
        for address in client.ip_addresses:
            ip_row = ClientIpRow(ip_address=address, mac_address=mac, vlan=client.vlan)
            ip_rows.setdefault((ip_row.ip_address, mac, ip_row.vlan), ip_row)
    return tuple(ip_rows.values()), tuple(mac_rows.values())

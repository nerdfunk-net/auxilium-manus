"""Response models of the client data REST API (``/client-data``)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClientObservation(_Out):
    """One MAC (and its IP) as seen by one device, in its newest collection."""

    mac_address: str
    device_name: str
    # The MAC-table port, or the ARP interface for an observation without a MAC-table entry.
    port: str | None
    vlan: str | None
    vrf: str | None
    ip_address: str | None
    hostname: str | None
    # Distinct MACs the device learned on ``port``; None for an ARP-only observation.
    macs_on_port: int | None
    # More MACs on the port than CLIENT_DATA_UPLINK_MAC_THRESHOLD: a trunk, not an access port.
    is_uplink: bool
    # The access port with the fewest MACs among this MAC's MAC-table observations.
    likely_location: bool
    session_id: str
    # When the port (MAC table) or the ARP entry was collected.
    collected_at: str | None
    # When the ARP collection that gave ``ip_address`` was collected; it can differ from
    # ``collected_at`` because ARP and the MAC table are current independently. None without an IP.
    ip_collected_at: str | None


class ClientDataPage(_Out):
    items: list[ClientObservation]
    total: int
    page: int
    page_size: int


class IpHistoryEntry(_Out):
    ip_address: str
    mac_address: str | None
    port: str | None
    vlan: str | None
    vrf: str | None
    device_name: str
    collected_at: str | None


class MacHistoryEntry(_Out):
    mac_address: str
    port: str | None
    vlan: str | None
    device_name: str
    ip_address: str | None
    collected_at: str | None


class HostnameHistoryEntry(_Out):
    hostname: str
    ip_address: str
    device_name: str
    collected_at: str | None


class ClientHistory(_Out):
    ip_history: list[IpHistoryEntry]
    mac_history: list[MacHistoryEntry]
    hostname_history: list[HostnameHistoryEntry]


class CollectionInfo(_Out):
    """Coverage of one device: when and how each table was last collected.

    A table is current from the newest collection that read it, so ARP and the MAC table can
    come from different runs. ``skipped`` (and no time) means it was never collected.
    """

    device_name: str
    # The newest of the two collection times.
    collected_at: str | None
    arp_collected_at: str | None
    mac_collected_at: str | None
    arp_status: str
    mac_status: str
    # VRF discovery belongs to the ARP collection.
    vrf_status: str
    vrf_count: int
    # Per discovered VRF: its ARP status and row count; None = VRFs were not discovered.
    vrfs: list[dict[str, Any]] | None
    arp_rows: int
    mac_rows: int

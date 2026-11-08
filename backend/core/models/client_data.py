from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ClientIpAddress(Base):
    """One ARP table entry seen by a device (``show ip arp``, default VRF or one VRF).

    ``session_id`` is the uuid of the workflow run that collected it; together with
    ``device_name`` it identifies one collection (see ``ClientDataCollection``).
    """

    __tablename__ = "client_ip_addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    # Dotted-quad (aabb.ccdd.eeff); None for an incomplete ARP entry.
    mac_address: Mapped[str | None] = mapped_column(String(20), nullable=True)
    interface: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vrf: Mapped[str | None] = mapped_column(String(64), nullable=True)  # None = default VRF
    # Derived from an SVI interface name (Vlan10 -> "10"); None for other interfaces.
    vlan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    device_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_client_ip_session_device", "session_id", "device_name"),
        Index("idx_client_ip_device", "device_name"),
        Index("idx_client_ip_mac", "mac_address"),
        Index("idx_client_ip_ip", "ip_address"),
        Index("idx_client_ip_vrf", "vrf"),
        Index("idx_client_ip_collected_at", "collected_at"),
    )


class ClientMacAddress(Base):
    """One MAC address table entry seen by a device (``show mac address-table``)."""

    __tablename__ = "client_mac_addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    mac_address: Mapped[str] = mapped_column(String(20), nullable=False)
    vlan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The port the MAC was learned on.
    port: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    device_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_client_mac_session_device", "session_id", "device_name"),
        Index("idx_client_mac_device", "device_name"),
        Index("idx_client_mac_mac", "mac_address"),
        Index("idx_client_mac_collected_at", "collected_at"),
    )


class ClientHostname(Base):
    """A DNS (PTR) hostname resolved for an IP address a device had in its ARP table."""

    __tablename__ = "client_hostnames"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    device_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_client_hostname_session_device", "session_id", "device_name"),
        Index("idx_client_hostname_ip", "ip_address"),
        Index("idx_client_hostname_hostname", "hostname"),
        Index("idx_client_hostname_collected_at", "collected_at"),
    )


class ClientDataCollection(Base):
    """One device's collection in one run, with the outcome of each command.

    Written even when the device returned no rows, so the newest collection of a device
    always supersedes older rows ("latest" is decided per device from this table), and
    so "this switch has no MAC table" can be told apart from "no MACs were learned".
    Statuses: ``ok`` | ``not_supported`` | ``no_template`` | ``skipped``.
    """

    __tablename__ = "client_data_collections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    arp_status: Mapped[str] = mapped_column(String(20), nullable=False, default="skipped")
    mac_status: Mapped[str] = mapped_column(String(20), nullable=False, default="skipped")
    vrf_status: Mapped[str] = mapped_column(String(20), nullable=False, default="skipped")
    vrf_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # [{"name", "status", "rows"}] per discovered VRF; NULL = not discovered (nullable JSON).
    vrfs: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    # The SSH target the collection came from. A later write for the same run and device name
    # from another target is a different device with the same name, not a retry. NULL = unknown.
    target_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    arp_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mac_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("session_id", "device_name", name="uq_client_data_collection_session"),
        Index("idx_client_data_collection_device_time", "device_name", "collected_at"),
        Index("idx_client_data_collection_collected_at", "collected_at"),
    )

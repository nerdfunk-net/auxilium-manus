"""Normalized per-device facts read from Cisco Catalyst Center.

Raw Intent API payloads stay inside ``services.catalyst_center``; steps only see these
frozen, whitelisted shapes. Every field is optional because the controller omits or blanks
values freely (and differs a little between releases).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Fact(BaseModel):
    model_config = ConfigDict(frozen=True)


class CatalystCenterDeviceDetails(_Fact):
    """``GET /network-device/{id}`` -- identity and inventory state."""

    id: str
    hostname: str | None = None
    management_ip: str | None = None
    platform_id: str | None = None
    serial_number: str | None = None
    family: str | None = None
    device_type: str | None = None
    role: str | None = None
    mac_address: str | None = None
    reachability_status: str | None = None
    reachability_failure_reason: str | None = None
    collection_status: str | None = None
    management_state: str | None = None
    support_level: str | None = None
    up_time: str | None = None
    boot_time: str | None = None
    last_updated: str | None = None
    location_name: str | None = None


class CatalystCenterSoftware(_Fact):
    """Software facts taken from the same ``/network-device/{id}`` record."""

    software_type: str | None = None
    software_version: str | None = None
    platform_id: str | None = None
    series: str | None = None
    description: str | None = None


class CatalystCenterInterface(_Fact):
    """One entry of ``GET /interface/network-device/{id}``."""

    name: str | None = None
    description: str | None = None
    status: str | None = None
    admin_status: str | None = None
    interface_type: str | None = None
    port_mode: str | None = None
    port_type: str | None = None
    media_type: str | None = None
    speed: str | None = None
    duplex: str | None = None
    mtu: int | None = None
    mac_address: str | None = None
    ipv4_address: str | None = None
    ipv4_mask: str | None = None
    vlan_id: str | None = None
    native_vlan_id: str | None = None
    voice_vlan: str | None = None


class CatalystCenterVlan(_Fact):
    """One entry of ``GET /network-device/{id}/vlan``."""

    vlan_number: int | None = None
    vlan_type: str | None = None
    interface_name: str | None = None
    ip_address: str | None = None
    prefix: str | None = None
    network_address: str | None = None
    number_of_ips: int | None = None


class CatalystCenterComplianceItem(_Fact):
    compliance_type: str | None = None
    status: str | None = None
    state: str | None = None
    last_sync_time: int | None = None
    remediation_supported: bool | None = None
    ack_status: str | None = None


class CatalystCenterCompliance(_Fact):
    """``GET /compliance/{id}`` (overall) plus ``/compliance/{id}/detail`` (per type)."""

    status: str | None = None
    last_update_time: int | None = None
    items: tuple[CatalystCenterComplianceItem, ...] = ()


class CatalystCenterHealth(_Fact):
    """``GET /device-detail`` -- health score and utilisation of one device."""

    overall_health: float | None = None
    cpu: float | None = None
    cpu_score: float | None = None
    memory: float | None = None
    memory_score: float | None = None
    communication_state: str | None = None
    collection_status: str | None = None
    ha_status: str | None = None
    stack_type: str | None = None
    ring_status: bool | None = None
    maintenance_mode: bool | None = None
    last_boot_time: int | None = None
    timestamp: int | None = None
    os_type: str | None = None
    software_version: str | None = None
    role: str | None = None


class CatalystCenterTopologyNode(_Fact):
    id: str
    label: str | None = None
    ip: str | None = None
    role: str | None = None
    family: str | None = None
    platform_id: str | None = None
    software_version: str | None = None
    device_type: str | None = None
    node_type: str | None = None


class CatalystCenterTopologyLink(_Fact):
    id: str | None = None
    source: str
    target: str
    start_port_name: str | None = None
    end_port_name: str | None = None
    start_port_speed: str | None = None
    end_port_speed: str | None = None
    status: str | None = None


class CatalystCenterTopology(_Fact):
    """A controller-wide graph; ``for_device`` slices it down to one device."""

    nodes: tuple[CatalystCenterTopologyNode, ...] = ()
    links: tuple[CatalystCenterTopologyLink, ...] = ()

    def for_device(self, device_id: str) -> dict[str, object]:
        """The device's own node and its links, each seen from the device's side."""
        by_id = {node.id: node for node in self.nodes}
        links: list[dict[str, object]] = []
        for link in self.links:
            if device_id not in (link.source, link.target):
                continue
            local_is_source = link.source == device_id
            remote = by_id.get(link.target if local_is_source else link.source)
            links.append(
                {
                    "link_id": link.id,
                    "local_port": link.start_port_name if local_is_source else link.end_port_name,
                    "local_speed": (
                        link.start_port_speed if local_is_source else link.end_port_speed
                    ),
                    "remote_port": link.end_port_name if local_is_source else link.start_port_name,
                    "remote_speed": (
                        link.end_port_speed if local_is_source else link.start_port_speed
                    ),
                    "remote_id": link.target if local_is_source else link.source,
                    "remote_name": remote.label if remote else None,
                    "remote_ip": remote.ip if remote else None,
                    "status": link.status,
                }
            )
        node = by_id.get(device_id)
        return {"node": node.model_dump(mode="json") if node else None, "links": links}

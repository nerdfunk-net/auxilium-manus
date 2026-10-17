"""Per-device detail facts from Cisco Catalyst Center (read-only).

Endpoints, all verified on the DevNet sandbox (see doc/CISCO_CATALYST_INTEGRATION.md):

- ``GET /network-device/{id}``               device record (also the source of the software facts)
- ``GET /interface/network-device/{id}``     interfaces
- ``GET /network-device/{id}/vlan``          VLAN interfaces
- ``GET /compliance/{id}`` and ``/compliance/{id}/detail``   overall and per-type compliance
"""

from __future__ import annotations

from typing import Any

from models.catalyst_center_facts import (
    CatalystCenterCompliance,
    CatalystCenterComplianceItem,
    CatalystCenterDeviceDetails,
    CatalystCenterInterface,
    CatalystCenterSoftware,
    CatalystCenterVlan,
)
from services.catalyst_center.client import CatalystCenterService
from services.catalyst_center.common.coerce import boolean, integer, text
from services.catalyst_center.common.exceptions import CatalystCenterAPIError
from services.catalyst_center.common.ids import safe_device_id
from services.catalyst_center.credentials import CatalystCenterCredentials

_INTENT = "/dna/intent/api/v1"
DEVICES_PATH = f"{_INTENT}/network-device"
INTERFACES_PATH = f"{_INTENT}/interface/network-device"
COMPLIANCE_PATH = f"{_INTENT}/compliance"


def _response(payload: Any, kind: type[dict] | type[list], what: str) -> Any:
    body = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(body, kind):
        raise CatalystCenterAPIError(f"Catalyst Center returned an unexpected {what} response")
    return body


def _records(body: list[Any]) -> list[dict[str, Any]]:
    return [entry for entry in body if isinstance(entry, dict)]


class CatalystCenterDetailsService:
    def __init__(
        self, client: CatalystCenterService, credentials: CatalystCenterCredentials
    ) -> None:
        self._client = client
        self._credentials = credentials

    async def _get(self, path: str) -> Any:
        return await self._client.request(self._credentials, "GET", path)

    async def get_device_and_software(
        self, device_id: str
    ) -> tuple[CatalystCenterDeviceDetails, CatalystCenterSoftware]:
        """One request serves both the ``device`` and the ``software`` facts."""
        safe_id = safe_device_id(device_id)
        record = _response(await self._get(f"{DEVICES_PATH}/{safe_id}"), dict, "device")
        details = CatalystCenterDeviceDetails(
            id=safe_id,
            hostname=text(record.get("hostname")),
            management_ip=text(record.get("managementIpAddress")),
            platform_id=text(record.get("platformId")),
            serial_number=text(record.get("serialNumber")),
            family=text(record.get("family")),
            device_type=text(record.get("type")),
            role=text(record.get("role")),
            mac_address=text(record.get("macAddress")),
            reachability_status=text(record.get("reachabilityStatus")),
            reachability_failure_reason=text(record.get("reachabilityFailureReason")),
            collection_status=text(record.get("collectionStatus")),
            management_state=text(record.get("managementState")),
            support_level=text(record.get("deviceSupportLevel")),
            up_time=text(record.get("upTime")),
            boot_time=text(record.get("bootDateTime")),
            last_updated=text(record.get("lastUpdated")),
            location_name=text(record.get("locationName")),
        )
        software = CatalystCenterSoftware(
            software_type=text(record.get("softwareType")),
            software_version=text(record.get("softwareVersion")),
            platform_id=text(record.get("platformId")),
            series=text(record.get("series")),
            description=text(record.get("description")),
        )
        return details, software

    async def get_interfaces(self, device_id: str) -> tuple[CatalystCenterInterface, ...]:
        body = _response(
            await self._get(f"{INTERFACES_PATH}/{safe_device_id(device_id)}"), list, "interface"
        )
        return tuple(
            CatalystCenterInterface(
                name=text(item.get("portName")),
                description=text(item.get("description")),
                status=text(item.get("status")),
                admin_status=text(item.get("adminStatus")),
                interface_type=text(item.get("interfaceType")),
                port_mode=text(item.get("portMode")),
                port_type=text(item.get("portType")),
                media_type=text(item.get("mediaType")),
                speed=text(item.get("speed")),
                duplex=text(item.get("duplex")),
                mtu=integer(item.get("mtu")),
                mac_address=text(item.get("macAddress")),
                ipv4_address=text(item.get("ipv4Address")),
                ipv4_mask=text(item.get("ipv4Mask")),
                vlan_id=text(item.get("vlanId")),
                native_vlan_id=text(item.get("nativeVlanId")),
                voice_vlan=text(item.get("voiceVlan")),
            )
            for item in _records(body)
        )

    async def get_vlans(self, device_id: str) -> tuple[CatalystCenterVlan, ...]:
        body = _response(
            await self._get(f"{DEVICES_PATH}/{safe_device_id(device_id)}/vlan"), list, "vlan"
        )
        return tuple(
            CatalystCenterVlan(
                vlan_number=integer(item.get("vlanNumber")),
                vlan_type=text(item.get("vlanType")),
                interface_name=text(item.get("interfaceName")),
                ip_address=text(item.get("ipAddress")),
                prefix=text(item.get("prefix")),
                network_address=text(item.get("networkAddress")),
                number_of_ips=integer(item.get("numberOfIPs")),
            )
            for item in _records(body)
        )

    async def get_compliance(self, device_id: str) -> CatalystCenterCompliance:
        safe_id = safe_device_id(device_id)
        overall = _response(await self._get(f"{COMPLIANCE_PATH}/{safe_id}"), dict, "compliance")
        detail = _response(
            await self._get(f"{COMPLIANCE_PATH}/{safe_id}/detail"), list, "compliance detail"
        )
        return CatalystCenterCompliance(
            status=text(overall.get("complianceStatus")),
            last_update_time=integer(overall.get("lastUpdateTime")),
            items=tuple(
                CatalystCenterComplianceItem(
                    compliance_type=text(item.get("complianceType")),
                    status=text(item.get("status")),
                    state=text(item.get("state")),
                    last_sync_time=integer(item.get("lastSyncTime")),
                    remediation_supported=boolean(item.get("remediationSupported")),
                    ack_status=text(item.get("ackStatus")),
                )
                for item in _records(detail)
            ),
        )

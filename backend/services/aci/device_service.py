"""Cisco ACI device inventory: leaf and spine switches of the fabric (never the APIC controllers).

Two reads per search - ``fabricNode`` (identity, role, model, serial, version, fabric state) and
``topSystem`` (management addresses, system state) - merged on the node id.

``fabricNode.address`` is the fabric-internal TEP address, not a management address. The
management IP is the out-of-band address, else the in-band one, else ``None``: a fabric that has
no node management addresses configured (the DevNet sandbox) simply has none to report.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from models.aci import AciDevice
from services.aci.common.coerce import integer, text, usable_ipv4
from services.aci.common.exceptions import AciTooManyDevicesError, AciValidationError
from services.aci.credentials import AciCredentials
from services.aci.device_filters import ALLOWED_ROLES, AciDeviceFilters

FABRIC_NODE_CLASS = "fabricNode"
TOP_SYSTEM_CLASS = "topSystem"

_DN = re.compile(r"topology/pod-(\d+)/node-(\d+)(?:/|$)")


class AciQueryClient(Protocol):
    async def query_class(
        self,
        credentials: AciCredentials,
        class_name: str,
        *,
        query_filter: str | None = None,
    ) -> list[dict[str, Any]]: ...

    async def get(
        self, credentials: AciCredentials, path: str, *, params: dict[str, Any] | None = None
    ) -> Any: ...

    async def login_info(self, credentials: AciCredentials, *, fresh: bool = False) -> Any: ...


def _role_filter(class_name: str, roles: tuple[str, ...]) -> str:
    """APIC ``query-target-filter`` for the roles (closed set, never user text)."""
    wanted = roles or ALLOWED_ROLES
    terms = [f'eq({class_name}.role,"{role}")' for role in wanted]
    return terms[0] if len(terms) == 1 else f"or({','.join(terms)})"


def normalize_device(
    fabric_node: dict[str, Any], top_system: dict[str, Any] | None
) -> AciDevice | None:
    """Build an :class:`AciDevice`, or ``None`` for a row that is not a usable leaf/spine."""
    role = text(fabric_node.get("role"))
    node_id = integer(fabric_node.get("id"))
    if role not in ALLOWED_ROLES or node_id is None:
        return None
    dn = text(fabric_node.get("dn"))
    match = _DN.search(dn or "")
    system = top_system or {}
    oob_ip = usable_ipv4(system.get("oobMgmtAddr"))
    inb_ip = usable_ipv4(system.get("inbMgmtAddr"))
    return AciDevice(
        node_id=node_id,
        name=text(fabric_node.get("name")) or f"node-{node_id}",
        role=role,  # type: ignore[arg-type]  # narrowed by the ALLOWED_ROLES check above
        pod_id=int(match.group(1)) if match else None,
        model=text(fabric_node.get("model")),
        serial_number=text(fabric_node.get("serial")),
        software_version=text(fabric_node.get("version")),
        fabric_state=text(fabric_node.get("fabricSt")),
        system_state=text(system.get("state")),
        tep_address=text(fabric_node.get("address")),
        management_ip=oob_ip or inb_ip,
        oob_ip=oob_ip,
        inb_ip=inb_ip,
        dn=dn,
        raw={"fabric_node": dict(fabric_node), "top_system": dict(top_system or {})},
    )


class AciDeviceService:
    """Read-only device search for one APIC source (credentials already resolved)."""

    def __init__(self, client: AciQueryClient, credentials: AciCredentials) -> None:
        self._client = client
        self._credentials = credentials

    async def search(
        self,
        filters: AciDeviceFilters | None = None,
        *,
        max_devices: int | None = None,
    ) -> list[AciDevice]:
        """Leaf/spine switches matching ``filters``, ordered by node id.

        ``max_devices`` fails (``AciTooManyDevicesError``) rather than truncating: a workflow
        acting on a silently incomplete target list is worse than a failed one.
        """
        if max_devices is not None and max_devices < 1:
            raise AciValidationError("max_devices must be 1 or higher")
        active = filters or AciDeviceFilters()
        nodes = await self._client.query_class(
            self._credentials,
            FABRIC_NODE_CLASS,
            query_filter=_role_filter(FABRIC_NODE_CLASS, active.roles),
        )
        systems = await self._client.query_class(
            self._credentials,
            TOP_SYSTEM_CLASS,
            query_filter=_role_filter(TOP_SYSTEM_CLASS, active.roles),
        )
        system_by_id = {
            node_id: system
            for system in systems
            if (node_id := integer(system.get("id"))) is not None
        }
        devices: list[AciDevice] = []
        for node in nodes:
            device = normalize_device(node, system_by_id.get(integer(node.get("id")) or -1))
            if device is not None and active.matches(device):
                devices.append(device)
        devices.sort(key=lambda item: item.node_id)
        if max_devices is not None and len(devices) > max_devices:
            raise AciTooManyDevicesError(max_devices)
        return devices

    async def preview_devices(
        self, filters: AciDeviceFilters, *, limit: int
    ) -> tuple[tuple[AciDevice, ...], bool]:
        """The first ``limit`` matches and whether more exist."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise AciValidationError("limit must be a positive whole number")
        found = await self.search(filters)
        return tuple(found[:limit]), len(found) > limit

    async def test_connection(self) -> str | None:
        """Log in afresh and prove the user can read the fabric inventory.

        Returns the APIC version reported at login. A login can succeed for a user who may read
        nothing, so one inventory row is requested as well; it is not merged or filtered.
        """
        info = await self._client.login_info(self._credentials, fresh=True)
        await self._client.get(
            self._credentials,
            f"/api/class/{FABRIC_NODE_CLASS}.json",
            params={"page": 0, "page-size": 1},
        )
        version = info.version
        return version if isinstance(version, str) and version else None

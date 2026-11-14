"""Interface redundancy groups (HSRP/VRRP) of the interface workflow.

A Nautobot redundancy group is a shared object (protocol, group id, virtual IP); every
interface that takes part has one association carrying its own priority. Peers therefore
reuse the group: it is found by protocol + group id + virtual IP and only created when no
such group exists, named by the caller's schema (``hsrp-{next}``). Nothing is ever deleted.

The virtual IP is created inside the same lock as the group (two peers of one run must not both
create it), a bare address is never given a guessed prefix length, and a priority the bag does not
carry never overwrites one that is stored in Nautobot.
"""

from __future__ import annotations

import asyncio
import logging
import weakref
from typing import Any

from services.nautobot.common.exceptions import NautobotAPIError
from services.nautobot.common.rest import rest_paginate, rest_query
from services.nautobot.devices.interface_workflow.base import InterfaceOpsBase
from services.nautobot.devices.interface_workflow.payload import DEFAULT_NAMESPACE, namespace_name
from services.nautobot.devices.interface_workflow.redundancy_naming import (
    literal_prefix,
    next_free_name,
)
from services.nautobot.devices.interface_workflow.state import InterfaceUpdateState

logger = logging.getLogger(__name__)

GROUPS_ENDPOINT = "dcim/interface-redundancy-groups/"
ASSOCIATIONS_ENDPOINT = "dcim/interface-redundancy-group-associations/"
GROUP_CONTENT_TYPE = "dcim.interfaceredundancygroup"
DEFAULT_PRIORITY = 100
_NAME_CONFLICT_ATTEMPTS = 3

# Devices of one run are written concurrently, so finding or creating a group (and its
# ``{next}`` number) is serialized. One lock per event loop: an asyncio.Lock is loop-bound.
_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)


def _allocation_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _LOCKS.get(loop)
    if lock is None:
        lock = _LOCKS[loop] = asyncio.Lock()
    return lock


def _is_conflict(exc: NautobotAPIError) -> bool:
    """A 400 that says the object (or its name) already exists."""
    return exc.http_status == 400 and (
        "name" in (exc.fields or ()) or "already exists" in str(exc).lower()
    )


class InterfaceRedundancyOps(InterfaceOpsBase):
    async def _existing_ip_by_host(self, host: str, namespace_id: str) -> str:
        """The one IP object with this host in the namespace (the mask is not known)."""
        query = rest_query(host=host, namespace=namespace_id, limit=2)
        response = await self.nautobot.rest_request(endpoint=f"ipam/ip-addresses/?{query}")
        rows = response.get("results") if isinstance(response, dict) else None
        if not rows:
            raise ValueError(
                f"virtual IP {host} has no prefix length and no such address exists in Nautobot: "
                f"give it one (for example {host}/24) so it can be created"
            )
        if len(rows) > 1:
            raise ValueError(
                f"virtual IP {host} has no prefix length and matches more than one address in "
                "Nautobot: give it the one to use (for example with its prefix length)"
            )
        return str(rows[0]["id"])

    async def _ensure_virtual_ip(
        self, group: dict[str, Any], interface: dict[str, Any], add_prefixes: bool
    ) -> str:
        """The VIP as a Nautobot IP address object (created when missing, never assigned).

        A bare address (no ``/len``) is only looked up: a guessed length would create a different
        object, and possibly a prefix. Another worker may create the address meanwhile, so one
        "already exists" answer is followed by one more look-up.
        """
        namespace = namespace_name(group.get("namespace")) or DEFAULT_NAMESPACE
        namespace_id = await self.common.resolve_namespace_id(namespace)
        address = group["virtual_ip"]["address"]
        if "/" not in address:
            return await self._existing_ip_by_host(address, namespace_id)
        for attempt in (1, 2):
            try:
                return await self.common.ensure_ip_address_exists(
                    ip_address=address,
                    namespace_id=namespace_id,
                    status_name=str(interface.get("status") or "active"),
                    add_prefixes_automatically=add_prefixes,
                )
            except NautobotAPIError as exc:
                if attempt == 2 or "already exists" not in str(exc).lower():
                    raise
        raise RuntimeError("unreachable")

    async def _find_group(self, protocol: str, group_id: str, vip_id: str) -> dict[str, Any] | None:
        query = rest_query(
            protocol=protocol, protocol_group_id=group_id, virtual_ip=vip_id, limit=50
        )
        rows = await rest_paginate(self.nautobot, f"{GROUPS_ENDPOINT}?{query}")
        return rows[0] if rows else None

    async def _existing_names(self, prefix: str) -> list[str]:
        params: dict[str, Any] = {"limit": 1000}
        if prefix:
            params["name__isw"] = prefix
        rows = await rest_paginate(self.nautobot, f"{GROUPS_ENDPOINT}?{rest_query(**params)}")
        return [str(row.get("name") or "") for row in rows]

    async def _create_group(
        self, group: dict[str, Any], vip_id: str, name_pattern: str, status: str
    ) -> dict[str, Any]:
        protocol = group["protocol"]
        status_id = await self.common.resolve_status_id(status, GROUP_CONTENT_TYPE)
        last_error: NautobotAPIError | None = None
        for _ in range(_NAME_CONFLICT_ATTEMPTS):
            names = await self._existing_names(literal_prefix(name_pattern, protocol))
            payload: dict[str, Any] = {
                "name": next_free_name(name_pattern, protocol, names),
                "protocol": protocol,
                "protocol_group_id": group["protocol_group_id"],
                "status": {"id": status_id},
                "virtual_ip": {"id": vip_id},
            }
            if group.get("description"):
                payload["description"] = str(group["description"])[:255]
            try:
                return await self.nautobot.rest_request(
                    endpoint=GROUPS_ENDPOINT, method="POST", data=payload
                )
            except NautobotAPIError as exc:
                if not _is_conflict(exc):
                    raise
                last_error = exc
                # Another worker may have created this very group (same protocol, group id and
                # virtual IP): then it is the one to use, and a new name would only fail again.
                existing = await self._find_group(protocol, group["protocol_group_id"], vip_id)
                if existing is not None:
                    return existing
                # Otherwise it was only the number that was taken: look again.
        raise last_error or RuntimeError("redundancy group name allocation failed")

    async def _find_or_create_group(
        self,
        group: dict[str, Any],
        interface: dict[str, Any],
        name_pattern: str,
        status: str,
        add_prefixes: bool,
    ) -> str:
        async with _allocation_lock():
            vip_id = await self._ensure_virtual_ip(group, interface, add_prefixes)
            existing = await self._find_group(group["protocol"], group["protocol_group_id"], vip_id)
            if existing is not None:
                return str(existing["id"])
            created = await self._create_group(group, vip_id, name_pattern, status)
            logger.info("Created redundancy group %s", created.get("name"))
            return str(created["id"])

    async def _ensure_association(
        self, interface_id: str, group_id: str, priority: int | None
    ) -> None:
        """Associate the interface with the group.

        ``priority=None`` (the bag has none, e.g. it was read from Nautobot) gives a new
        association the default and leaves an existing one exactly as it is.
        """
        query = rest_query(interface=interface_id, interface_redundancy_group=group_id)
        rows = await rest_paginate(self.nautobot, f"{ASSOCIATIONS_ENDPOINT}?{query}")
        if not rows:
            await self.nautobot.rest_request(
                endpoint=ASSOCIATIONS_ENDPOINT,
                method="POST",
                data={
                    "interface": {"id": interface_id},
                    "interface_redundancy_group": {"id": group_id},
                    "priority": DEFAULT_PRIORITY if priority is None else priority,
                },
            )
            return
        if priority is not None and rows[0].get("priority") != priority:
            await self.nautobot.rest_request(
                endpoint=f"{ASSOCIATIONS_ENDPOINT}{rows[0]['id']}/",
                method="PATCH",
                data={"priority": priority},
            )

    async def _apply_redundancy_groups(
        self,
        *,
        interfaces: list[dict[str, Any]],
        state: InterfaceUpdateState,
        name_pattern: str | None,
        group_status: str,
        add_prefixes_automatically: bool,
    ) -> None:
        """Create/reuse the groups of every interface and associate the interface with them."""
        if not name_pattern:
            return
        for interface in interfaces:
            name = str(interface.get("name") or "").strip()
            groups = interface.get("interface_redundancy_groups")
            interface_id = state.interface_id_map.get(name)
            if not name or not groups or not interface_id:
                continue
            for group in groups:
                try:
                    group_id = await self._find_or_create_group(
                        group, interface, name_pattern, group_status, add_prefixes_automatically
                    )
                    priority = group.get("priority")
                    await self._ensure_association(
                        interface_id,
                        group_id,
                        priority if isinstance(priority, int) else None,
                    )
                except Exception as exc:
                    logger.error("Redundancy group of %s failed: %s", name, exc)
                    if name not in state.failed_interfaces:
                        state.failed_interfaces.append(name)
                    state.warnings.append(
                        f"Interface {name}: failed to write redundancy group "
                        f"{group.get('protocol_group_id')!r}: {exc}"
                    )

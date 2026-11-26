"""Redundancy groups (HSRP, VRRP, GLBP, CARP) of the steps that write interfaces to Nautobot.

The ``redundancy_groups`` setting of ``add-to-nautobot`` (Add to Nautobot) and
``update-nautobot-device`` (Update Device): ``{"enabled": bool, "name_pattern": "hsrp-{next}",
"status": "Active"}``; off (the default) means no group is written. And the reader that cleans the
groups of a device's Nautobot attribute bag for the write. See
``services/nautobot/devices/interface_workflow/redundancy_ops.py``.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

from services.nautobot.devices.interface_workflow.payload import namespace_name
from services.nautobot.devices.interface_workflow.redundancy_naming import (
    DEFAULT_NAME_PATTERN,
    validate_name_pattern,
)
from workflow_steps.common.interface_values import lower_text, strip_empty
from workflow_steps.common.step_flags import parse_bool_flag

logger = logging.getLogger(__name__)


def ip_namespace_name(ip_item: dict[str, Any]) -> str | None:
    """Namespace of a bag IP: ``parent.namespace.name`` (Nautobot shape), else ``namespace``."""
    parent = ip_item.get("parent")
    namespace = parent.get("namespace") if isinstance(parent, dict) else None
    if isinstance(namespace, dict):
        name = strip_empty(namespace.get("name"))
        if isinstance(name, str):
            return name
    return namespace_name(ip_item.get("namespace"))


REDUNDANCY_PROTOCOLS = frozenset({"hsrp", "vrrp", "glbp", "carp"})


def _containing_namespace(vip: str, ip_addresses: list[dict[str, Any]]) -> str | None:
    """Namespace of the interface address whose network contains ``vip``, if there is one."""
    try:
        vip_ip = ipaddress.ip_address(vip.split("/")[0])
    except ValueError:
        return None
    for entry in ip_addresses:
        try:
            network = ipaddress.ip_interface(str(entry.get("address"))).network
        except ValueError:
            logger.debug("Ignoring unparsable interface address %r", entry.get("address"))
            continue
        if vip_ip in network:
            namespace = entry.get("namespace")
            return namespace if isinstance(namespace, str) else None
    return None


def redundancy_groups_from_bag(
    raw: Any, ip_addresses: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Clean an interface's ``interface_redundancy_groups`` for the Nautobot write.

    Accepts what ``config-to-attributes`` builds and what ``get-nautobot-attributes`` reads
    (``virtual_ip`` as text or ``{"address": ...}``, any protocol case, an int group id). An entry
    without a known protocol, a group id or a virtual IP cannot be matched in Nautobot and is
    left out.

    - The virtual IP keeps the length it has. A bare address is **not** given a guessed prefix
      length: a wrong one would create a different IP object (and possibly a prefix) and split the
      peers' group; the write step looks the address up or refuses it.
    - ``description`` is the device's own text (Cisco group name, VRRP description). The ``name``
      of an entry is never written back as the description: from Nautobot it is the inventory
      name (``hsrp-1``), not text of the device.
    - ``namespace`` is the virtual IP's own (from Nautobot) or that of the interface address whose
      network contains it, else unset (the write step uses ``Global``).
    - ``priority`` is kept only when the bag has one (a Nautobot read has it per association).
    """
    if not isinstance(raw, list):
        return []
    groups: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        protocol = lower_text(item.get("protocol"))
        group_id = item.get("protocol_group_id")
        group_id = (
            None
            if isinstance(group_id, bool)
            else strip_empty(str(group_id) if isinstance(group_id, int) else group_id)
        )
        vip = item.get("virtual_ip")
        address = strip_empty(vip.get("address") if isinstance(vip, dict) else vip)
        if protocol not in REDUNDANCY_PROTOCOLS or not group_id or not isinstance(address, str):
            continue
        group: dict[str, Any] = {
            "protocol": protocol,
            "protocol_group_id": str(group_id),
            "virtual_ip": {"address": address},
        }
        namespace = (ip_namespace_name(vip) if isinstance(vip, dict) else None) or (
            _containing_namespace(address, ip_addresses)
        )
        if namespace:
            group["namespace"] = namespace
        description = strip_empty(item.get("description"))
        if isinstance(description, str):
            group["description"] = description
        priority = item.get("priority")
        if isinstance(priority, int) and not isinstance(priority, bool):
            group["priority"] = priority
        groups.append(group)
    return groups


# --- the step setting --------------------------------------------------------------------------

DEFAULT_REDUNDANCY_STATUS = "Active"


def default_redundancy_groups() -> dict[str, Any]:
    """The setting as a step's ``get_config()`` lists it."""
    return {
        "enabled": False,
        "name_pattern": DEFAULT_NAME_PATTERN,
        "status": DEFAULT_REDUNDANCY_STATUS,
    }


def parse_redundancy_groups(
    config: dict[str, Any], *, step_id: str, interfaces_source: str
) -> tuple[str | None, str]:
    """``(name pattern or None when off, status)``; ``ValueError`` for an unusable setting."""
    raw = config.get("redundancy_groups")
    if raw is None:
        return None, DEFAULT_REDUNDANCY_STATUS
    if not isinstance(raw, dict):
        raise ValueError(f"{step_id}: redundancy_groups must be an object")
    if not parse_bool_flag(raw, "enabled", default=False):
        return None, DEFAULT_REDUNDANCY_STATUS
    if interfaces_source != "nautobot_origin":
        raise ValueError(
            f"{step_id}: redundancy_groups needs interfaces_source 'nautobot_origin' "
            "(the groups are read from the interfaces in the Nautobot attribute bag)"
        )
    pattern = str(raw.get("name_pattern") or DEFAULT_NAME_PATTERN).strip()
    problem = validate_name_pattern(pattern)
    if problem:
        raise ValueError(f"{step_id}: redundancy_groups.name_pattern: {problem}")
    status = str(raw.get("status") or DEFAULT_REDUNDANCY_STATUS).strip()
    return pattern, status

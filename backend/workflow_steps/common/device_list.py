"""Shared helpers for identity-only inventory steps that build ``DeviceContext``
values directly from operator-supplied names/IPs — no external inventory system
involved. Used by ``get-from-list`` (a fixed canvas-configured list) and
``get-from-user`` (a list typed by the operator at run-trigger time via a
``static_attributes`` run input). Keeping the parsing/validation/device-id
rules here means the two steps can never quietly drift apart.

Every entry may carry a ``network_driver`` (the Netmiko platform the SSH steps connect
with). A device without one gets ``DEFAULT_NETWORK_DRIVER`` so a workflow that never
touches an inventory system can still reach its devices.
"""

from __future__ import annotations

import hashlib
from typing import Any, NamedTuple

from models.workflow_context import Capability, DeviceContext, DeviceStatus, bare_hostname
from services.nautobot.common.validators import validate_ip_address
from services.network.netmiko.platform import UnsupportedPlatformError, resolve_netmiko_device_type

DEFAULT_NETWORK_DRIVER = "cisco_ios"

# attribute_bags keys the workflow engine reserves for itself — see
# workflow_steps/common/attribute_write.py::_RESERVED_BAG_NAMES. A caller must
# never pass one of these as `attribute_bag_name`: a device created with an
# existing "run_input" bag key would make services/workflow_context/run_inputs.py
# ::seed_run_input_bag treat it as already-seeded and silently skip stamping the
# real run inputs onto it.
_RESERVED_ATTRIBUTE_BAG_NAMES = frozenset({"parsed", "run_input"})


class DeviceEntry(NamedTuple):
    name: str | None
    ip_address: str | None
    network_driver: str | None = None


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def validated_driver(value: Any, *, where: str, step: str) -> str | None:
    """The canonical Netmiko type of the driver (``ios`` -> ``cisco_ios``), or None when blank.

    ``ValueError`` when Netmiko has no such driver.
    """
    driver = _clean_str(value)
    if driver is None:
        return None
    try:
        return resolve_netmiko_device_type(network_driver=driver)
    except UnsupportedPlatformError as exc:
        raise ValueError(f"{step}: unknown network driver '{driver}' ({where})") from exc


def _entry_key(entry: DeviceEntry) -> tuple[str | None, str | None, str | None]:
    """Dedup key. Drivers are canonical and defaulted by the time entries are built."""
    return (entry.name.casefold() if entry.name else None, entry.ip_address, entry.network_driver)


def normalize_device_entries(
    raw_devices: Any, *, default_driver: str = DEFAULT_NETWORK_DRIVER
) -> list[DeviceEntry]:
    """Normalize a fixed canvas ``devices`` list (``get-from-list``'s
    ``pluginConfig.devices``) — each row a bare string or a ``{name,
    ip_address, network_driver}`` dict. A row without a driver gets ``default_driver``; drivers are
    resolved to their canonical Netmiko type first, then entries are deduplicated by name, IP
    address and driver. Raises ``ValueError`` on a malformed IP address or an unknown driver.
    """
    if not isinstance(raw_devices, list):
        return []

    entries: list[DeviceEntry] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for index, item in enumerate(raw_devices):
        driver_raw: Any = None
        if isinstance(item, str):
            name = _clean_str(item)
            ip_address = None
        elif isinstance(item, dict):
            name = _clean_str(item.get("name"))
            ip_address = _clean_str(item.get("ip_address"))
            driver_raw = item.get("network_driver")
        else:
            continue

        if name is None and ip_address is None:
            continue

        if ip_address is not None and not validate_ip_address(ip_address):
            raise ValueError(f"get-from-list: invalid IP address '{ip_address}' (row {index + 1})")

        driver = (
            validated_driver(driver_raw, where=f"row {index + 1}", step="get-from-list")
            or default_driver
        )
        entry = DeviceEntry(name=name, ip_address=ip_address, network_driver=driver)
        if _entry_key(entry) in seen:
            continue
        seen.add(_entry_key(entry))
        entries.append(entry)

    return entries


def parse_device_list_text(
    raw_value: Any, *, default_driver: str = DEFAULT_NETWORK_DRIVER
) -> list[DeviceEntry]:
    """Parse a run-input value (``get-from-user``'s ``run_inputs[device_param]``)
    into device entries — one device per line.

    Line syntax:
      - ``name,ip_address[,network_driver]`` — the second part must be a valid IP
        address and the third a Netmiko driver (``ValueError`` naming the offending
        line otherwise). Either of the first two may be empty (``name,,junos``);
        a missing driver becomes ``default_driver``. Drivers are canonicalized
        (``ios`` -> ``cisco_ios``) before entries are deduplicated.
      - a bare token with no comma — auto-detected: a valid IP address format
        becomes ``ip_address``, anything else becomes ``name`` (names are
        never checked for existence — there is no inventory system to check
        against).

    Blank lines are ignored. Entries are deduplicated by
    name, IP address and driver, same as ``normalize_device_entries``.
    """
    text = "" if raw_value is None else str(raw_value)

    entries: list[DeviceEntry] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        driver: str = default_driver
        if "," in line:
            parts = line.split(",")
            if len(parts) > 3:  # noqa: PLR2004  # name, ip_address, network_driver
                raise ValueError(
                    f"get-from-user: expected name,ip_address,network_driver (line {line_number})"
                )
            name = _clean_str(parts[0])
            ip_address = _clean_str(parts[1])
            if ip_address is not None and not validate_ip_address(ip_address):
                raise ValueError(
                    f"get-from-user: invalid IP address '{ip_address}' (line {line_number})"
                )
            if len(parts) == 3:  # noqa: PLR2004
                driver = (
                    validated_driver(parts[2], where=f"line {line_number}", step="get-from-user")
                    or default_driver
                )
        elif validate_ip_address(line):
            name = None
            ip_address = line
        else:
            name = line
            ip_address = None

        if name is None and ip_address is None:
            continue

        entry = DeviceEntry(name=name, ip_address=ip_address, network_driver=driver)
        if _entry_key(entry) in seen:
            continue
        seen.add(_entry_key(entry))
        entries.append(entry)

    return entries


def device_context_from_entry(
    entry: DeviceEntry,
    *,
    index: int,
    node_id: str,
    source: str = "list",
    attribute_bag_name: str | None = None,
    default_driver: str | None = None,
) -> DeviceContext:
    """Build an identity-only ``DeviceContext`` from a single parsed entry.

    ``source`` namespaces the device id / ``DeviceContext.source`` so devices
    built by different callers (``get-from-list`` vs ``get-from-user``) never
    collide even when derived from the same ``node_id``/name/IP/index.

    ``attribute_bag_name`` (defaults to ``source``) is the ``attribute_bags``
    key the entry itself is stamped under — kept independent of ``source`` so
    a caller can pass ``source="run_input"`` (a meaningful provenance label)
    without accidentally colliding with the reserved ``"run_input"``
    attribute-bags key (see the module docstring above).

    The device's ``network_driver`` is the entry's own, else ``default_driver``,
    else ``DEFAULT_NETWORK_DRIVER``.
    """
    display_name = entry.name or entry.ip_address
    assert display_name is not None  # noqa: S101  # narrowing; caller already filtered empties

    bag_name = attribute_bag_name or source
    if bag_name in _RESERVED_ATTRIBUTE_BAG_NAMES:
        raise ValueError(
            f"device_context_from_entry: attribute_bag_name {bag_name!r} is reserved by "
            "the workflow engine; pass an explicit non-reserved attribute_bag_name"
        )

    digest = hashlib.sha256(
        f"{node_id}:{entry.name or ''}:{entry.ip_address or ''}:{index}".encode()
    ).hexdigest()[:32]
    device_id = f"{source}-{digest}"
    network_driver = entry.network_driver or default_driver or DEFAULT_NETWORK_DRIVER

    return DeviceContext(
        id=device_id,
        name=display_name,
        hostname=bare_hostname(entry.ip_address, display_name),
        primary_ip4=entry.ip_address,
        network_driver=network_driver,
        source=source,
        source_id=node_id,
        attribute_bags={
            bag_name: {
                "name": entry.name,
                "ip_address": entry.ip_address,
                "network_driver": network_driver,
                "index": index,
            }
        },
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )

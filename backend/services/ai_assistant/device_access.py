"""The one module through which the assistant reaches a device (doc/AI_TOOL_CHAIN.md §29).

Everything that touches Nautobot device data or Netmiko for the assistant lives here, and
``test_ai_device_guard`` fails if another module in ``services/ai_assistant`` imports Netmiko. The
model never supplies a host: it names a device, ``DbDeviceResolver`` finds it in the inventory the
user may read, and the host, platform and driver come from there. Credentials are the user's own
(``CredentialsService`` with ``acting_user_id``), chosen by the user in the confirm card.

Running happens only from the confirm endpoint (``device_exec_service``), never from a tool.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import service_factory
from core.database import SessionLocal
from core.safe_hosts import validate_device_host
from dependencies import nautobot_credentials_from_source_id
from models.netmiko import NetmikoRunCommandsRequest
from models.sources_nautobot import DeviceInfo
from services.auth.rbac_service import RBACService
from services.credentials.credentials_service import CredentialsService
from services.network.netmiko.connection import DEFAULT_CONFIG_READ_TIMEOUT
from services.network.netmiko.platform import (
    UnsupportedPlatformError,
    resolve_netmiko_device_type,
)
from services.network.netmiko.preview_service import NetmikoPreviewService
from services.settings.settings_service import SettingsService

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 50
# Commands that print a whole configuration (or a whole diagnostic dump) take longer than a
# normal show command; they get the config read timeout the Netmiko config getters use.
_LONG_COMMANDS = (
    "show running-config",
    "show startup-config",
    "show configuration",
    "show tech-support",
)
# The device types the user may pick when the inventory's platform is not recognised: exactly the
# Netmiko device types this app maps platform names to (pinned by a test).
DEVICE_DRIVERS = (
    "arista_eos",
    "cisco_asa",
    "cisco_ios",
    "cisco_nxos",
    "cisco_xe",
    "cisco_xr",
    "hp_comware",
    "juniper_junos",
)


class DeviceAccessError(Exception):
    """Base class; the message is safe to show to the user and to the model."""


class DeviceAccessDeniedError(DeviceAccessError):
    def __init__(self) -> None:
        super().__init__("You are not allowed to read the device inventory")


class DeviceNotFoundError(DeviceAccessError):
    def __init__(self) -> None:
        super().__init__("No device with exactly that name is in the inventory")


class DeviceAmbiguousError(DeviceAccessError):
    def __init__(self) -> None:
        super().__init__("More than one device has that name; ask the user which one is meant")


class DeviceUnsupportedPlatformError(DeviceAccessError):
    def __init__(self) -> None:
        super().__init__(
            "No SSH driver is known for this device's platform. Choose the device type "
            "(for example cisco_ios) when you confirm."
        )


class DeviceNoAddressError(DeviceAccessError):
    def __init__(self) -> None:
        super().__init__("The device has no usable management address in the inventory")


@dataclass(frozen=True)
class ResolvedDevice:
    source_id: str
    device_id: str
    name: str
    host: str
    platform: str | None
    network_driver: str | None


@dataclass(frozen=True)
class DeviceCommandOutput:
    success: bool
    error: str | None
    outputs: tuple[tuple[str, str], ...]


def driver_known(device: ResolvedDevice) -> bool:
    """Whether Netmiko can pick a driver from the inventory's platform / network driver."""
    try:
        resolve_netmiko_device_type(network_driver=device.network_driver, platform=device.platform)
    except UnsupportedPlatformError:
        return False
    return True


def netmiko_device_type(network_driver: str | None, platform: str | None) -> str | None:
    """The Netmiko device type for an inventory driver / platform, or ``None`` when unknown.

    The neighbour catalogue picks its commands by device family; it asks here so that this stays
    the only module that touches the Netmiko platform map.
    """
    try:
        return resolve_netmiko_device_type(network_driver=network_driver, platform=platform)
    except UnsupportedPlatformError:
        return None


class DeviceResolver(Protocol):
    async def resolve(self, name: str) -> ResolvedDevice: ...


class DeviceCommandRunner(Protocol):
    async def run(
        self,
        device: ResolvedDevice,
        commands: list[str],
        *,
        credential_id: int,
        user_id: int,
        network_driver: str | None = None,
    ) -> DeviceCommandOutput: ...


def _host_of(primary_ip4: str | None) -> str:
    text = (primary_ip4 or "").strip()
    if not text:
        raise DeviceNoAddressError
    try:
        host = str(ipaddress.ip_interface(text).ip)
        return validate_device_host(host)
    except ValueError as exc:
        raise DeviceNoAddressError from exc


def _host_or_empty(primary_ip4: str | None) -> str:
    """The management host, or ``""`` when the inventory has none (a read that never connects)."""
    try:
        return _host_of(primary_ip4)
    except DeviceNoAddressError:
        return ""


def select_device(
    name: str, found: list[tuple[str, DeviceInfo]], *, require_address: bool = True
) -> ResolvedDevice:
    """The one device called exactly ``name`` among ``(source_id, device)`` search results.

    An exact (case-sensitive) name wins; otherwise a single case-insensitive match is accepted.
    Substring matches never count. Anything else is not found or ambiguous. With
    ``require_address=False`` a device without a usable address is returned with ``host=""``
    (for reads that never open a session, such as the config backup).
    """
    exact = [(s, d) for s, d in found if d.name == name]
    matches = exact or [(s, d) for s, d in found if (d.name or "").casefold() == name.casefold()]
    if not matches:
        raise DeviceNotFoundError
    if len(matches) > 1:
        raise DeviceAmbiguousError
    source_id, device = matches[0]
    return ResolvedDevice(
        source_id=source_id,
        device_id=device.id,
        name=device.name or name,
        host=(_host_of if require_address else _host_or_empty)(device.primary_ip4),
        platform=device.platform,
        network_driver=device.platform_network_driver,
    )


def select_device_by_ip(
    found: list[tuple[str, DeviceInfo]],
) -> ResolvedDevice | None:
    """The one device that has the address, ``None`` when none does.

    Raises ``DeviceAmbiguousError`` when two different devices share the address, so an address
    never silently picks one of them.
    """
    if not found:
        return None
    if len({(source_id, device.id) for source_id, device in found}) > 1:
        raise DeviceAmbiguousError
    source_id, device = found[0]
    return ResolvedDevice(
        source_id=source_id,
        device_id=device.id,
        name=device.name or "",
        host=_host_of(device.primary_ip4),
        platform=device.platform,
        network_driver=device.platform_network_driver,
    )


class DbDeviceResolver:
    """Finds a device by name in the Nautobot sources, as the calling user."""

    def __init__(self, user_id: int) -> None:
        self._user_id = user_id

    def _load_sources(self) -> list[tuple[str, Any]]:
        """``(source_id, credentials)`` of every configured Nautobot source."""
        with SessionLocal() as db:
            if not RBACService(db).has_permission(self._user_id, "sources.nautobot", "read"):
                raise DeviceAccessDeniedError
            sources = SettingsService(db).list_nautobot_source_summaries().sources
            loaded: list[tuple[str, Any]] = []
            for source in sources:
                try:
                    loaded.append(
                        (
                            source.source_id,
                            nautobot_credentials_from_source_id(source.source_id, db),
                        )
                    )
                except Exception:  # an unusable source must not hide the others
                    logger.info("AI assistant: Nautobot source %r unavailable", source.source_id)
            return loaded

    async def _search(self, credentials: Any, name: str) -> list[DeviceInfo]:
        service = service_factory.build_nautobot_source_service(credentials)
        return await service.search_devices_by_name(name, MAX_CANDIDATES)

    async def _find(self, name: str) -> list[tuple[str, DeviceInfo]]:
        sources = await asyncio.to_thread(self._load_sources)
        found: list[tuple[str, DeviceInfo]] = []
        for source_id, credentials in sources:
            found.extend((source_id, d) for d in await self._search(credentials, name))
        return found

    async def resolve(self, name: str) -> ResolvedDevice:
        return select_device(name, await self._find(name))

    async def resolve_by_ip(self, ip: str) -> ResolvedDevice | None:
        """The inventory device whose management address is ``ip``, or ``None`` if there is none.

        Needs the same permission as a lookup by name, so an address cannot be used to reach the
        inventory (or to skip it) without ``sources.nautobot:read``.
        """
        sources = await asyncio.to_thread(self._load_sources)
        found: list[tuple[str, DeviceInfo]] = []
        for source_id, credentials in sources:
            service = service_factory.build_nautobot_source_service(credentials)
            found.extend((source_id, d) for d in await service.find_devices_by_primary_ip(ip))
        return select_device_by_ip(found)

    async def resolve_without_address(self, name: str) -> ResolvedDevice:
        """Like ``resolve`` but a device with no management address is accepted (``host=""``)."""
        return select_device(name, await self._find(name), require_address=False)


class DbDeviceCommandRunner:
    """Runs already-checked commands through the Netmiko preview service as the user."""

    async def run(
        self,
        device: ResolvedDevice,
        commands: list[str],
        *,
        credential_id: int,
        user_id: int,
        network_driver: str | None = None,
    ) -> DeviceCommandOutput:
        # ``network_driver`` is the user's own choice in the confirm card (a closed list); it wins
        # over what the inventory says, like a driver override on a workflow step.
        request = NetmikoRunCommandsRequest(
            host=device.host,
            platform=device.platform,
            network_driver=network_driver or device.network_driver,
            credential_id=credential_id,
            commands=commands,
            use_textfsm=False,
        )
        long = any(c.lower().startswith(_LONG_COMMANDS) for c in commands)
        with SessionLocal() as db:
            service = NetmikoPreviewService(CredentialsService(db))
            try:
                response = await service.run_commands(
                    request,
                    acting_user_id=user_id,
                    host_from_inventory=True,
                    read_timeout=DEFAULT_CONFIG_READ_TIMEOUT if long else None,
                )
            except UnsupportedPlatformError as exc:
                raise DeviceUnsupportedPlatformError from exc
        return DeviceCommandOutput(
            success=response.success,
            error=response.error,
            outputs=tuple((entry.name, entry.raw) for entry in response.commands),
        )

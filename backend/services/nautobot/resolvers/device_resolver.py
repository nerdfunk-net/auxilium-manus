"""
Device resolver for device and device-related entity resolution.
"""

import logging
from typing import Any

from ..common.exceptions import NautobotAmbiguousMatchError, NautobotAPIError
from ..common.validators import is_valid_uuid
from .base_resolver import BaseResolver

logger = logging.getLogger(__name__)


def _raise_on_graphql_errors(result: dict[str, Any], what: str) -> None:
    """A response carrying ``errors`` may hold partial data: never read it as "no device"."""
    if result.get("errors"):
        logger.error("GraphQL error looking up %s: %s", what, result["errors"])
        raise NautobotAPIError(
            "Nautobot's GraphQL API reported an error for this query", code="graphql_error"
        )


class DeviceResolver(BaseResolver):
    """Resolver for device and device-related entities."""

    async def resolve_device_by_name(self, device_name: str) -> str | None:
        """
        Resolve device UUID from device name using GraphQL.

        This picks the device a write goes to, so it is strict (P-N1, W2-01): a device with
        another name is never taken, two devices of that name raise
        ``NautobotAmbiguousMatchError``, and a GraphQL or transport error is raised, not
        reported as "not found".

        Returns:
            Device UUID if found, None if no device has that name
        """
        logger.info("Looking up device by name: %s", device_name)

        query = """
        query GetDeviceByName($name: [String]) {
          devices(name: $name) {
            id
            name
          }
        }
        """
        result = await self.nautobot.graphql_query(query, {"name": [device_name]})
        _raise_on_graphql_errors(result, "device by name")

        devices = (result.get("data") or {}).get("devices") or []
        # never fall back to a device that has another name
        ids = {
            str(device["id"])
            for device in devices
            if device.get("name") == device_name and device.get("id")
        }
        if len(ids) > 1:
            raise NautobotAmbiguousMatchError(
                f"{len(ids)} Nautobot devices are named {device_name!r}"
            )
        if not ids:
            logger.warning("No device found with name: %s", device_name)
            return None
        device_id = next(iter(ids))
        logger.info("Found device by name '%s': %s", device_name, device_id)
        return device_id

    async def resolve_device_by_ip(self, ip_address: str) -> str | None:
        """
        Resolve device UUID from primary IPv4 address using GraphQL.

        Looks up the IP address object and returns the device it's assigned to as primary IP.
        Strict like ``resolve_device_by_name``: two devices with that primary IP raise
        ``NautobotAmbiguousMatchError``, and a GraphQL or transport error is raised.

        Returns:
            Device UUID if found, None otherwise
        """
        logger.info("Looking up device by primary IPv4: %s", ip_address)

        # Query for IP address and get the device it's assigned to as primary IP
        query = """
        query GetIPAddress($address: [String]) {
          ip_addresses(address: $address) {
            id
            address
            primary_ip4_for {
              id
              name
            }
          }
        }
        """
        result = await self.nautobot.graphql_query(query, {"address": [ip_address]})
        _raise_on_graphql_errors(result, "IP address")

        ids: set[str] = set()
        for ip_obj in (result.get("data") or {}).get("ip_addresses") or []:
            devices = ip_obj.get("primary_ip4_for")
            # primary_ip4_for can be a list or a single device
            if isinstance(devices, dict):
                devices = [devices]
            for device in devices or []:
                if device.get("id"):
                    ids.add(str(device["id"]))

        if len(ids) > 1:
            raise NautobotAmbiguousMatchError(
                f"{len(ids)} Nautobot devices have primary IP {ip_address}"
            )
        if not ids:
            logger.warning("IP address %s is not set as primary IP for any device", ip_address)
            return None
        device_id = next(iter(ids))
        logger.info("Found device by IP '%s': %s", ip_address, device_id)
        return device_id

    async def resolve_device_id(
        self,
        device_id: str | None = None,
        device_name: str | None = None,
        ip_address: str | None = None,
        matching_strategy: str = "exact",
    ) -> str | None:
        """
        Resolve device UUID from any available identifier.

        Tries in order: device_id (if valid), device_name (using matching_strategy), ip_address

        Args:
            device_id: Device UUID (if already known)
            device_name: Device name to search for
            ip_address: Primary IPv4 address to search for
            matching_strategy: How to match by name — "exact" (default),
                "contains", or "starts_with"

        Returns:
            Device UUID if found, None otherwise
        """
        # If device_id is already provided, validate and return it
        if device_id:
            # Basic UUID validation
            if is_valid_uuid(device_id):
                logger.debug("Using provided device ID: %s", device_id)
                return device_id
            else:
                logger.warning("Invalid device ID format: %s", device_id)

        # Try resolving by name using the configured strategy
        if device_name:
            if matching_strategy == "contains":
                resolved = await self.resolve_device_by_name_contains(device_name)
            elif matching_strategy == "starts_with":
                resolved = await self.resolve_device_by_name_starts_with(device_name)
            else:
                # Default: exact match
                resolved = await self.resolve_device_by_name(device_name)

            if resolved:
                return resolved

        # Try resolving by IP address
        if ip_address:
            resolved = await self.resolve_device_by_ip(ip_address)
            if resolved:
                return resolved

        logger.error("Could not resolve device ID from any identifier")
        return None

    async def resolve_device_by_name_contains(self, device_name: str) -> str | None:
        """
        Resolve device UUID by searching for devices whose name *contains* the given string.

        When multiple devices match, the first result is returned and a warning is logged.

        Args:
            device_name: Partial device name to search for

        Returns:
            Device UUID if exactly one match found, None otherwise
        """
        try:
            logger.info("Looking up device by name (contains): %s", device_name)

            # Nautobot GraphQL supports name__ic for case-insensitive contains
            query = """
            query GetDeviceByNameContains($name: String) {
              devices(name__ic: $name) {
                id
                name
              }
            }
            """
            variables = {"name": device_name}
            result = await self.nautobot.graphql_query(query, variables)

            if "errors" in result:
                logger.error(
                    "GraphQL error looking up device by name (contains): %s",
                    result["errors"],
                )
                return None

            devices = result.get("data", {}).get("devices", [])
            if not devices:
                logger.warning("No device found whose name contains: %s", device_name)
                return None

            if len(devices) > 1:
                names = [d.get("name") for d in devices]
                logger.warning(
                    "Multiple devices (%s) match name contains '%s': %s — using first match",
                    len(devices),
                    device_name,
                    names,
                )

            device_id = devices[0].get("id")
            logger.info(
                "Found device by name contains '%s': %s (%s)",
                device_name,
                devices[0].get("name"),
                device_id,
            )
            return device_id

        except Exception as e:
            logger.error("Error resolving device by name (contains): %s", e, exc_info=True)
            return None

    async def resolve_device_by_name_starts_with(self, device_name: str) -> str | None:
        """
        Resolve device UUID by searching for devices whose name *starts with* the given string.

        When multiple devices match, the first result is returned and a warning is logged.

        Args:
            device_name: Name prefix to search for

        Returns:
            Device UUID if a match is found, None otherwise
        """
        try:
            logger.info("Looking up device by name (starts with): %s", device_name)

            # Nautobot GraphQL supports name__isw for case-insensitive starts-with
            query = """
            query GetDeviceByNameStartsWith($name: [String]) {
              devices(name__isw: $name) {
                id
                name
              }
            }
            """
            variables = {"name": device_name}
            result = await self.nautobot.graphql_query(query, variables)

            if "errors" in result:
                logger.error(
                    "GraphQL error looking up device by name (starts_with): %s",
                    result["errors"],
                )
                return None

            devices = result.get("data", {}).get("devices", [])
            if not devices:
                logger.warning("No device found whose name starts with: %s", device_name)
                return None

            if len(devices) > 1:
                names = [d.get("name") for d in devices]
                logger.warning(
                    "Multiple devices (%s) match name starts_with '%s': %s — using first match",
                    len(devices),
                    device_name,
                    names,
                )

            device_id = devices[0].get("id")
            logger.info(
                "Found device by name starts_with '%s': %s (%s)",
                device_name,
                devices[0].get("name"),
                device_id,
            )
            return device_id

        except Exception as e:
            logger.error("Error resolving device by name (starts_with): %s", e, exc_info=True)
            return None

    async def resolve_device_type_id(
        self, model: str, manufacturer: str | None = None
    ) -> str | None:
        """
        Resolve device type (model) to UUID using GraphQL.

        Args:
            model: Device type model name
            manufacturer: Optional manufacturer name for disambiguation

        Returns:
            Device type UUID if found, None otherwise
        """
        try:
            logger.info(
                "Resolving device type '%s'%s",
                model,
                f" from manufacturer '{manufacturer}'" if manufacturer else "",
            )

            # Build query with optional manufacturer filter
            if manufacturer:
                query = """
                query GetDeviceType($model: [String], $manufacturer: [String]) {
                  device_types(model: $model, manufacturer: $manufacturer) {
                    id
                    model
                    manufacturer {
                      name
                    }
                  }
                }
                """
                variables = {"model": [model], "manufacturer": [manufacturer]}
            else:
                query = """
                query GetDeviceType($model: [String]) {
                  device_types(model: $model) {
                    id
                    model
                    manufacturer {
                      name
                    }
                  }
                }
                """
                variables = {"model": [model]}

            result = await self.nautobot.graphql_query(query, variables)

            if "errors" in result:
                logger.error("GraphQL error resolving device type: %s", result["errors"])
                return None

            device_types = result.get("data", {}).get("device_types", [])
            if device_types and len(device_types) > 0:
                device_type = device_types[0]
                device_type_id = device_type["id"]
                mfr_name = device_type.get("manufacturer", {}).get("name", "unknown")
                logger.info(
                    "Resolved device type '%s' (%s) to UUID %s",
                    model,
                    mfr_name,
                    device_type_id,
                )
                return device_type_id

            logger.warning("Device type not found: %s", model)
            return None

        except Exception as e:
            logger.error("Error resolving device type: %s", e, exc_info=True)
            return None

    async def get_device_type_display(self, device_type_id: str) -> str | None:
        """
        Get device type display name from UUID using REST API.

        Args:
            device_type_id: Device type UUID

        Returns:
            Device type display name (e.g., "Cisco Catalyst 9300-48P") if found, None otherwise
        """
        try:
            logger.debug("Fetching device type display for UUID: %s", device_type_id)

            result = await self.nautobot.rest_request(
                endpoint=f"dcim/device-types/{device_type_id}/", method="GET"
            )

            if result:
                # Try display field first (most descriptive), fall back to model
                display_name = result.get("display") or result.get("model")
                if display_name:
                    logger.debug(
                        "Device type UUID %s -> display: %s",
                        device_type_id,
                        display_name,
                    )
                    return display_name

            logger.warning("Device type not found for UUID: %s", device_type_id)
            return None

        except Exception as e:
            logger.error("Error fetching device type display: %s", e, exc_info=True)
            return None

    async def find_interface_with_ip(
        self, device_name: str, ip_address: str
    ) -> tuple[str, str] | None:
        """
        Find the interface that currently has a specific IP address on a device.

        Args:
            device_name: Name of the device
            ip_address: IP address to search for (in CIDR notation, e.g., "10.0.0.1/24")

        Returns:
            Tuple of (interface_id, interface_name) if found, None otherwise
        """
        try:
            logger.info("Finding interface with IP %s on device %s", ip_address, device_name)

            query = """
            query ($filter_device: [String], $filter_address: [String]) {
              devices(name: $filter_device) {
                id
                name
                interfaces(ip_addresses: $filter_address) {
                  id
                  name
                }
              }
            }
            """
            variables = {
                "filter_device": [device_name],
                "filter_address": [ip_address],
            }

            result = await self.nautobot.graphql_query(query, variables)

            if "errors" in result:
                logger.error("GraphQL error finding interface with IP: %s", result["errors"])
                return None

            devices = result.get("data", {}).get("devices", [])
            if not devices or len(devices) == 0:
                logger.warning("Device '%s' not found", device_name)
                return None

            device = devices[0]
            interfaces = device.get("interfaces", [])

            if not interfaces or len(interfaces) == 0:
                logger.info(
                    "No interface found with IP %s on device %s",
                    ip_address,
                    device_name,
                )
                return None

            # Return the first interface with this IP
            interface = interfaces[0]
            interface_id = interface.get("id")
            interface_name = interface.get("name")

            logger.info(
                "Found interface '%s' (ID: %s) with IP %s",
                interface_name,
                interface_id,
                ip_address,
            )
            return (interface_id, interface_name)

        except Exception as e:
            logger.error("Error finding interface with IP: %s", e, exc_info=True)
            return None

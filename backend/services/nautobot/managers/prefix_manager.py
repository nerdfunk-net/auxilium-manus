"""
Prefix lifecycle manager.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from services.nautobot.common.rest import rest_paginate, rest_query

from ..common.exceptions import NautobotAPIError, is_duplicate_error
from ..common.utils import normalize_tags
from ..common.validators import is_valid_uuid
from .location_assignments import (
    LOCATIONS_MODES,
    LocationsMode,
    PartialUpdateError,
    apply_locations,
    missing_locations,
    reference_id,
)

if TYPE_CHECKING:
    from services.nautobot.api_protocol import NautobotApi

    from ..resolvers.metadata_resolver import MetadataResolver
    from ..resolvers.network_resolver import NetworkResolver

logger = logging.getLogger(__name__)

_ASSIGNMENTS_ENDPOINT = "ipam/prefix-location-assignments/"


def _is_network(
    row: Mapping[str, Any], wanted: ipaddress.IPv4Network | ipaddress.IPv6Network
) -> bool:
    """True when the row's ``prefix`` is the same network as ``wanted`` (compared as networks)."""
    try:
        return ipaddress.ip_network(str(row.get("prefix") or ""), strict=True) == wanted
    except ValueError:
        return False


# Fields that hold a related object's id; a UUID is compared and sent in lower case.
_ID_FIELDS = frozenset({"status", "role"})


async def _resolve_namespace_ref(network_resolver, namespace: str) -> str:
    if is_valid_uuid(namespace):
        logger.debug("Namespace is already a UUID: %s", namespace)
        return namespace
    return await network_resolver.resolve_namespace_id(namespace)


async def _find_prefix_id(nautobot, prefix: str, namespace_id: str) -> str | None:
    prefix_search_endpoint = (
        f"ipam/prefixes/?{rest_query(prefix=prefix, namespace=namespace_id, format='json')}"
    )
    prefix_result = await nautobot.rest_request(endpoint=prefix_search_endpoint, method="GET")
    if prefix_result and prefix_result.get("count", 0) > 0:
        return prefix_result["results"][0]["id"]
    return None


async def _attach_optional_location(
    metadata_resolver,
    prefix_data: dict,
    location: str,
) -> None:
    if is_valid_uuid(location):
        prefix_data["location"] = location
        return
    location_id = await metadata_resolver.resolve_location_id(location)
    if location_id:
        prefix_data["location"] = location_id
    else:
        logger.warning(
            "Location '%s' not found, prefix will be created without location",
            location,
        )


async def _build_prefix_create_payload(
    *,
    metadata_resolver,
    prefix: str,
    namespace_id: str,
    status_id: str,
    prefix_type: str,
    location: str | None,
    description: str | None,
    kwargs: dict,
) -> dict:
    prefix_data: dict[str, Any] = {
        "prefix": prefix,
        "namespace": namespace_id,
        "status": status_id,
        "type": prefix_type,
    }

    if description:
        prefix_data["description"] = description

    if location:
        await _attach_optional_location(metadata_resolver, prefix_data, location)

    optional_uuid_fields = ["role", "parent", "tenant", "vlan", "rir"]
    for field in optional_uuid_fields:
        if field in kwargs and kwargs[field]:
            value = kwargs[field]
            if is_valid_uuid(value):
                prefix_data[field] = value
            else:
                logger.warning("Field '%s' should be a UUID, got: %s", field, value)

    if "tags" in kwargs and kwargs["tags"]:
        prefix_data["tags"] = normalize_tags(kwargs["tags"])

    if "custom_fields" in kwargs and kwargs["custom_fields"]:
        prefix_data["custom_fields"] = kwargs["custom_fields"]

    return prefix_data


class PrefixManager:
    """Manager for IP prefix lifecycle operations."""

    def __init__(
        self,
        nautobot_service: NautobotApi,
        network_resolver: NetworkResolver,
        metadata_resolver: MetadataResolver,
    ):
        """
        Initialize the prefix manager.

        Args:
            nautobot_service: NautobotService instance for API calls
            network_resolver: NetworkResolver instance for resolution
            metadata_resolver: MetadataResolver instance for status resolution
        """
        self.nautobot = nautobot_service
        self.network_resolver = network_resolver
        self.metadata_resolver = metadata_resolver

    async def ensure_prefix_exists(
        self,
        prefix: str,
        namespace: str = "Global",
        status: str = "active",
        prefix_type: str = "network",
        location: str | None = None,
        description: str | None = None,
        **kwargs,
    ) -> str:
        """Ensure IP prefix exists; return existing or newly created UUID."""
        logger.info("Ensuring prefix exists: %s in namespace %s", prefix, namespace)

        namespace_id = await _resolve_namespace_ref(self.network_resolver, namespace)
        existing_id = await _find_prefix_id(self.nautobot, prefix, namespace_id)
        if existing_id:
            logger.info("Prefix already exists: %s", existing_id)
            return existing_id

        logger.info("Creating new prefix: %s", prefix)
        status_id = await self.metadata_resolver.resolve_status_id(
            status, content_type="ipam.prefix"
        )
        prefix_data = await _build_prefix_create_payload(
            metadata_resolver=self.metadata_resolver,
            prefix=prefix,
            namespace_id=namespace_id,
            status_id=status_id,
            prefix_type=prefix_type,
            location=location,
            description=description,
            kwargs=kwargs,
        )

        try:
            result = await self.nautobot.rest_request(
                endpoint="ipam/prefixes/", method="POST", data=prefix_data
            )
        except NautobotAPIError as exc:
            if is_duplicate_error(exc):
                # lost the race to a concurrent creator (fan-out children): use its prefix
                concurrent_id = await _find_prefix_id(self.nautobot, prefix, namespace_id)
                if concurrent_id:
                    logger.info("Prefix created concurrently: %s", concurrent_id)
                    return concurrent_id
            raise
        if not result or "id" not in result:
            raise NautobotAPIError(f"Failed to create prefix {prefix}: No ID returned")

        prefix_id = result["id"]
        logger.info("Created new prefix: %s with ID: %s", prefix, prefix_id)
        return prefix_id

    async def find_prefixes(self, prefix: str, namespace_id: str | None = None) -> list[str]:
        """Ids of the prefixes with this network, in one namespace when given (unique in one).

        The search uses the canonical text Nautobot stores (``2001:DB8::/32`` is looked up as
        ``2001:db8::/32``), and a row whose ``prefix`` is not that network is dropped: the exact
        filter is not a guarantee, and the caller updates the id of the one row it gets.

        Raises:
            ValueError: If ``prefix`` is not a network address (host bits set also count).
        """
        wanted = ipaddress.ip_network(prefix.strip(), strict=True)
        params: dict[str, Any] = {"prefix": str(wanted), "limit": 1000, "format": "json"}
        if namespace_id:
            params["namespace"] = namespace_id
        rows = await rest_paginate(self.nautobot, f"ipam/prefixes/?{rest_query(**params)}")
        return [str(row["id"]) for row in rows if row.get("id") and _is_network(row, wanted)]

    async def missing_locations(self, prefix_id: str, locations: Sequence[str]) -> list[str]:
        """The ids in ``locations`` the prefix is not assigned to yet (a read; nothing is written).

        This is what ``update_prefix(..., locations_mode="add")`` would add, for a dry run.

        Raises:
            ValueError: If ``prefix_id`` is not a UUID.
        """
        if not is_valid_uuid(prefix_id.lower()):
            raise ValueError("prefix_id is not a Nautobot UUID")
        return await missing_locations(
            self.nautobot, _ASSIGNMENTS_ENDPOINT, "prefix", prefix_id, locations
        )

    async def update_prefix(
        self,
        prefix_id: str,
        fields: Mapping[str, str],
        *,
        locations: Sequence[str] = (),
        locations_mode: LocationsMode = "replace",
    ) -> bool:
        """Update an existing prefix; only the values that differ are sent.

        Args:
            prefix_id: Prefix UUID
            fields: Nautobot REST fields to set (``status`` and ``role`` as ids, ``description``
                as text)
            locations: Location ids to apply in ``locations_mode``; empty leaves them alone
            locations_mode: ``replace`` sets the exact list, ``add`` keeps the current ones and
                adds, ``remove`` drops the given ones

        Returns:
            True when something was written, False when the prefix already had every value.

        Raises:
            ValueError: If ``prefix_id`` is not a UUID or the mode is unknown.
            NautobotNotFoundError: If the prefix does not exist.
            PartialUpdateError: If a later write failed after an earlier one was stored.
            NautobotAPIError: If Nautobot refuses the change.
        """
        if not is_valid_uuid(prefix_id.lower()):
            raise ValueError("prefix_id is not a Nautobot UUID")
        if locations_mode not in LOCATIONS_MODES:
            raise ValueError("locations_mode is not valid")
        current = await self.nautobot.rest_request(
            endpoint=f"ipam/prefixes/{prefix_id}/?format=json", method="GET"
        )
        wanted = {
            key: value.lower() if key in _ID_FIELDS and is_valid_uuid(value.lower()) else value
            for key, value in fields.items()
        }
        changes = {
            key: value for key, value in wanted.items() if reference_id(current.get(key)) != value
        }
        applied: list[str] = []
        try:
            if changes:
                logger.info("Updating prefix %s fields=%s", prefix_id, sorted(changes))
                await self.nautobot.rest_request(
                    endpoint=f"ipam/prefixes/{prefix_id}/", method="PATCH", data=changes
                )
                applied.append("fields")
            relocated = await apply_locations(
                self.nautobot, _ASSIGNMENTS_ENDPOINT, "prefix", prefix_id, locations, locations_mode
            )
        except PartialUpdateError as exc:
            raise PartialUpdateError([*applied, *exc.applied]) from exc.__cause__
        except Exception as exc:
            # Something is stored already: say so instead of reporting a plain failure.
            if applied:
                raise PartialUpdateError(applied) from exc
            raise
        return bool(changes) or relocated

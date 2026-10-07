"""Get-or-create for Nautobot reference data (locations, device types).

Used by the ``add-nautobot-metadata`` workflow step. Every public method is
idempotent: an object that already exists is returned with ``created=False``
instead of raising, so a workflow can run again (or fan out over devices that
share one location) safely. Names are matched case-insensitively and a valid UUID
passes through without a lookup, as in ``DeviceCreationService``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from services.nautobot.api_protocol import NautobotApi
from services.nautobot.common.exceptions import NautobotAPIError, is_duplicate_error
from services.nautobot.common.validators import is_valid_uuid

logger = logging.getLogger(__name__)

_LOCATION_CONTENT_TYPE = "dcim.location"
_DEVICE_CONTENT_TYPE = "dcim.device"
# Nautobot reports unique_together violations as "The fields a, b must make a unique set."
# — a phrasing the shared ``is_duplicate_error`` keywords do not cover.
_UNIQUE_SET_MARKER = "unique set"


class MetadataReferenceNotFoundError(ValueError):
    """A referenced Nautobot object (location type, manufacturer, ...) does not exist."""


class MetadataConflictError(ValueError):
    """Nautobot rejected a create as a duplicate, yet no matching object can be found."""


@dataclass(frozen=True)
class EnsureResult:
    id: str
    name: str
    created: bool


@dataclass(frozen=True)
class DeviceTypeResult:
    id: str
    model: str
    created: bool
    manufacturer: str
    role: str
    platform: str | None
    role_id: str
    platform_id: str | None


def _is_duplicate(exc: Exception) -> bool:
    return isinstance(exc, NautobotAPIError) and (
        is_duplicate_error(exc) or _UNIQUE_SET_MARKER in str(exc).lower()
    )


def _nested_id(value: Any) -> str | None:
    if isinstance(value, dict):
        nested = value.get("id")
        return str(nested) if nested else None
    return str(value) if value else None


class MetadataCreationService:
    """Ensure locations and device types exist in Nautobot (REST only)."""

    def __init__(self, nautobot: NautobotApi) -> None:
        self.nautobot = nautobot

    async def ensure_location(
        self,
        *,
        location_type: str,
        name: str,
        status: str,
        description: str = "",
        parent: str | None = None,
    ) -> EnsureResult:
        location_type_id, _ = await self._resolve(
            "dcim/location-types/", location_type, "Location type"
        )
        status_id, _ = await self._resolve(
            "extras/statuses/",
            status,
            "Status",
            content_type=_LOCATION_CONTENT_TYPE,
        )
        parent_id: str | None = None
        if parent:
            parent_id, _ = await self._resolve("dcim/locations/", parent, "Parent location")

        existing = await self._find_location(name, location_type_id, parent_id)
        if existing:
            return EnsureResult(id=str(existing["id"]), name=name, created=False)

        payload: dict[str, Any] = {
            "location_type": location_type_id,
            "name": name,
            "status": status_id,
        }
        if description:
            payload["description"] = description
        if parent_id:
            payload["parent"] = parent_id

        try:
            created = await self.nautobot.rest_request(
                "dcim/locations/", method="POST", data=payload
            )
        except Exception as exc:
            if not _is_duplicate(exc):
                raise
            raced = await self._find_location(name, location_type_id, parent_id)
            if not raced:
                raise MetadataConflictError(
                    f"Location '{name}' already exists in Nautobot under the same parent "
                    "with a different location type"
                ) from exc
            logger.info("Location '%s' was created concurrently — reusing it", name)
            return EnsureResult(id=str(raced["id"]), name=name, created=False)
        return EnsureResult(id=str(created["id"]), name=name, created=True)

    async def ensure_device_type(
        self,
        *,
        manufacturer: str,
        model: str,
        height: int,
        role: str,
        platform: str | None = None,
    ) -> DeviceTypeResult:
        manufacturer_id, manufacturer_name = await self._resolve(
            "dcim/manufacturers/", manufacturer, "Manufacturer"
        )
        role_id, role_name = await self._resolve(
            "extras/roles/", role, "Role", content_type=_DEVICE_CONTENT_TYPE
        )
        platform_name: str | None = None
        platform_id: str | None = None
        if platform:
            platform_id, platform_name = await self._resolve(
                "dcim/platforms/", platform, "Platform"
            )

        existing = await self._find_device_type(model, manufacturer_id)
        if existing:
            created = False
            device_type_id = str(existing["id"])
        else:
            payload = {"manufacturer": manufacturer_id, "model": model, "u_height": height}
            try:
                response = await self.nautobot.rest_request(
                    "dcim/device-types/", method="POST", data=payload
                )
                created = True
                device_type_id = str(response["id"])
            except Exception as exc:
                if not _is_duplicate(exc):
                    raise
                raced = await self._find_device_type(model, manufacturer_id)
                if not raced:
                    raise
                logger.info("Device type '%s' was created concurrently — reusing it", model)
                created = False
                device_type_id = str(raced["id"])

        return DeviceTypeResult(
            id=device_type_id,
            model=model,
            created=created,
            manufacturer=manufacturer_name,
            role=role_name,
            platform=platform_name,
            role_id=role_id,
            platform_id=platform_id,
        )

    async def _list(
        self, endpoint: str, name: str, content_type: str | None
    ) -> list[dict[str, Any]]:
        # ``name__ic`` (icontains): the plain ``name=`` filter is case-sensitive, so it would
        # miss "cisco" vs "Cisco". The exact case-insensitive match happens locally.
        query = f"name__ic={quote(name, safe='')}&limit=0"
        if content_type:
            query += f"&content_types={content_type}"
        response = await self.nautobot.rest_request(f"{endpoint}?{query}")
        return list((response or {}).get("results") or [])

    async def _resolve(
        self,
        endpoint: str,
        value: str,
        label: str,
        *,
        content_type: str | None = None,
    ) -> tuple[str, str]:
        """Return ``(uuid, display name)`` for a name or UUID; raise when it is unknown."""
        if is_valid_uuid(value):
            return value, value
        for item in await self._list(endpoint, value, content_type):
            item_name = str(item.get("name") or "")
            if item_name.lower() == value.lower():
                return str(item["id"]), item_name
        raise MetadataReferenceNotFoundError(f"{label} '{value}' not found in Nautobot")

    async def _find_location(
        self, name: str, location_type_id: str, parent_id: str | None
    ) -> dict[str, Any] | None:
        for item in await self._list("dcim/locations/", name, None):
            if str(item.get("name") or "").lower() != name.lower():
                continue
            if _nested_id(item.get("location_type")) != location_type_id:
                continue
            # A top-level request must not match a same-named location under a parent.
            if _nested_id(item.get("parent")) != parent_id:
                continue
            return item
        return None

    async def _find_device_type(self, model: str, manufacturer_id: str) -> dict[str, Any] | None:
        query = f"model__ic={quote(model, safe='')}&limit=0"
        response = await self.nautobot.rest_request(f"dcim/device-types/?{query}")
        for item in (response or {}).get("results") or []:
            if str(item.get("model") or "").lower() != model.lower():
                continue
            if _nested_id(item.get("manufacturer")) == manufacturer_id:
                return item
        return None

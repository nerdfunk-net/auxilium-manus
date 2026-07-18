"""Nautobot source metadata — custom field and field-value lookups."""

from __future__ import annotations

import logging
from typing import Any

from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials

logger = logging.getLogger(__name__)


class NautobotSourceMetadataService:
    """Fetches Nautobot custom-field definitions and per-field value lists."""

    def __init__(self, nautobot: NautobotService, credentials: NautobotCredentials) -> None:
        self._nautobot = nautobot
        self._credentials = credentials
        self._custom_fields_cache: list[dict[str, Any]] | None = None

    async def get_custom_fields(self) -> list[dict[str, Any]]:
        if self._custom_fields_cache is not None:
            return self._custom_fields_cache

        try:
            response = await self._nautobot.rest_request(
                "extras/custom-fields/?content_types=dcim.device",
                self._credentials,
            )
            if not response or "results" not in response:
                logger.error("Invalid REST response for custom fields")
                return []

            transformed_fields = []
            for field in response["results"]:
                field_name = field.get("key") or field.get("name", "")
                label = field.get("label", field_name)
                if isinstance(label, dict):
                    label = label.get("display") or label.get("value") or str(label)
                field_type = field.get("type", "text")
                if isinstance(field_type, dict):
                    field_type = (
                        field_type.get("value") or field_type.get("label") or str(field_type)
                    )
                transformed_fields.append(
                    {
                        "name": str(field_name),
                        "label": str(label) if label else str(field_name),
                        "type": str(field_type),
                    }
                )

            self._custom_fields_cache = transformed_fields
            return self._custom_fields_cache
        except Exception as exc:
            logger.error("Error getting custom fields: %s", exc)
            return []

    async def get_field_values(self, field_name: str) -> list[dict[str, str]]:
        try:
            if field_name == "name":
                return []
            if field_name.startswith("cf_"):
                return await self._get_custom_field_values(field_name)
            if field_name == "custom_fields":
                return await self._get_custom_field_list()
            return await self._get_standard_field_values(field_name)
        except Exception as exc:
            logger.error("Error getting field values for '%s': %s", field_name, exc)
            return []

    async def _get_custom_field_values(self, field_name: str) -> list[dict[str, str]]:
        cf_key = field_name[3:]
        custom_fields = await self.get_custom_fields()
        cf_info = next((cf for cf in custom_fields if cf.get("name") == cf_key), None)

        if cf_info and cf_info.get("type") == "select":
            try:
                choices_response = await self._nautobot.rest_request(
                    f"extras/custom-field-choices/?custom_field={cf_key}",
                    self._credentials,
                )
                if choices_response and "results" in choices_response:
                    values = [
                        {
                            "value": str(choice.get("value", "")),
                            "label": str(choice.get("value", "")),
                        }
                        for choice in choices_response["results"]
                        if choice.get("value")
                    ]
                    values.sort(key=lambda item: (item.get("label") or "").lower())
                    return values
            except Exception as exc:
                logger.error("Error fetching choices for custom field '%s': %s", cf_key, exc)
        return []

    async def _get_custom_field_list(self) -> list[dict[str, str]]:
        custom_fields = await self.get_custom_fields()
        values = [
            {
                "value": f"cf_{cf.get('name', '')}",
                "label": cf.get("label") or cf.get("name", ""),
            }
            for cf in custom_fields
            if cf.get("name")
        ]
        values.sort(key=lambda item: (item.get("label") or "").lower())
        return values

    async def _get_standard_field_values(self, field_name: str) -> list[dict[str, str]]:
        endpoint_map = {
            "location": "dcim/locations/?limit=0",
            "role": "extras/roles/?content_types=dcim.device&limit=0",
            "status": "extras/statuses/?content_types=dcim.device&limit=0",
            "device_type": "dcim/device-types/?limit=0&depth=1",
            "manufacturer": "dcim/manufacturers/?limit=0",
            "platform": "dcim/platforms/?limit=0",
            "tag": "extras/tags/?content_types=dcim.device&limit=0",
            "has_primary": None,
            "ip_prefix": None,
            "primary_prefix": None,
        }

        if field_name == "has_primary":
            return [{"value": "true", "label": "true"}, {"value": "false", "label": "false"}]

        endpoint = endpoint_map.get(field_name)
        if not endpoint:
            logger.warning("No endpoint defined for field: %s", field_name)
            return []

        response = await self._nautobot.rest_request(endpoint, self._credentials)
        if not response or "results" not in response:
            return []

        results = response["results"]
        values: list[dict[str, str]] = []

        if field_name == "device_type":
            for device_type in results:
                manufacturer_data = device_type.get("manufacturer")
                manufacturer_name = (
                    manufacturer_data.get("name", "Unknown")
                    if isinstance(manufacturer_data, dict)
                    else "Unknown"
                )
                model = device_type.get("model", device_type.get("name", "Unknown"))
                values.append({"value": model, "label": f"{manufacturer_name} {model}"})
        else:
            for item in results:
                name = item.get("name", "")
                if name:
                    values.append({"value": name, "label": name})

        values.sort(key=lambda item: (item.get("label") or "").lower())
        return values

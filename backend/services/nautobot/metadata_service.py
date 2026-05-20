"""Nautobot metadata REST operations (custom fields, choices)."""

from __future__ import annotations

import logging
from typing import Any

from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials

logger = logging.getLogger(__name__)


class NautobotMetadataService:
    def __init__(self, nautobot: NautobotService, credentials: NautobotCredentials) -> None:
        self.nautobot = nautobot
        self.credentials = credentials

    async def get_device_custom_fields(self) -> list[dict[str, Any]]:
        result = await self.nautobot.rest_request(
            "extras/custom-fields/?content_types=dcim.device",
            self.credentials,
        )
        return result.get("results", [])

    async def get_custom_field_choices(self, custom_field_name: str) -> list[dict[str, Any]]:
        result = await self.nautobot.rest_request(
            f"extras/custom-field-choices/?custom_field={custom_field_name}",
            self.credentials,
        )
        return result.get("results", [])

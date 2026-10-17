"""Nautobot location types — read-only REST listing for the location-type picker."""

from __future__ import annotations

from typing import Any

from services.nautobot.common.rest import rest_paginate
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient


class NautobotLocationTypesService:
    """Thin wrapper over Nautobot's ``/api/dcim/location-types/`` REST surface."""

    def __init__(self, client: CredentialsBoundNautobotClient) -> None:
        self._client = client

    async def list_location_types(self) -> list[dict[str, Any]]:
        return await rest_paginate(self._client, "dcim/location-types/?limit=1000")

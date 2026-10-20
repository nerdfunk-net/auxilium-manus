"""Nautobot statuses — read-only REST listing for the status picker."""

from __future__ import annotations

from typing import Any, Literal, get_args

from services.nautobot.common.rest import rest_paginate, rest_query
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient

# Object types whose statuses a step can pick. The content type is interpolated into a request
# path, so only these values are ever sent.
StatusContentType = Literal["ipam.ipaddress", "ipam.prefix"]
STATUS_CONTENT_TYPES: tuple[str, ...] = get_args(StatusContentType)


class NautobotStatusesService:
    """Thin wrapper over Nautobot's ``/api/extras/statuses/`` REST surface."""

    def __init__(self, client: CredentialsBoundNautobotClient) -> None:
        self._client = client

    async def list_statuses(self, content_type: StatusContentType) -> list[dict[str, Any]]:
        if content_type not in STATUS_CONTENT_TYPES:
            raise ValueError(f"unsupported status content type: {content_type!r}")
        query = rest_query(content_types=content_type, limit=1000, format="json")
        return await rest_paginate(self._client, f"extras/statuses/?{query}")

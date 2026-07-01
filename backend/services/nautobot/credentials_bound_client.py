"""Nautobot client bound to per-request credentials.

Cockpit device services expect ``rest_request`` / ``graphql_query`` without a
credentials argument. Workflow steps resolve credentials from configured sources
and use this adapter so copied cockpit code can run unchanged.
"""

from __future__ import annotations

from typing import Any

from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials


class CredentialsBoundNautobotClient:
    """Duck-types cockpit's NautobotService using explicit credentials."""

    def __init__(
        self,
        service: NautobotService,
        credentials: NautobotCredentials,
    ) -> None:
        self._service = service
        self._credentials = credentials

    async def graphql_query(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._service.graphql_query(query, variables, self._credentials)

    async def rest_request(
        self,
        endpoint: str,
        method: str = "GET",
        data: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]:
        return await self._service.rest_request(
            endpoint,
            self._credentials,
            method=method,
            data=data,
        )

"""Structural type for a Nautobot API handle with credentials already bound."""

from __future__ import annotations

from typing import Any, Protocol


class NautobotApi(Protocol):
    """What the resolvers, managers and device services call.

    Implemented by ``CredentialsBoundNautobotClient``. ``NautobotService`` itself takes
    ``credentials`` on every call and therefore does not satisfy this.
    """

    async def graphql_query(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def rest_request(
        self,
        endpoint: str,
        method: str = "GET",
        data: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]: ...

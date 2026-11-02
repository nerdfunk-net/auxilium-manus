"""The ``nautobot_read`` GraphQL transport on top of the app's ``NautobotService``.

Used by the AI assistant tools and by workflow steps that share the library's queries
(``get-virtual-chassis``), so the SSRF policy, TLS setting and credential handling stay in
``NautobotService`` and a failure becomes a short fixed sentence, never upstream text.
"""

from __future__ import annotations

import logging
from typing import Any

from nautobot_read.client import GraphQLClient
from nautobot_read.client import NautobotError as QueryError

from services.nautobot.common.exceptions import NautobotAPIError
from services.nautobot.common.exceptions import NautobotError as BackendNautobotError
from services.nautobot.credentials import NautobotCredentials

logger = logging.getLogger(__name__)

__all__ = ["NautobotServiceClient", "failure_message"]

_STATUS_MESSAGES = {
    401: "Nautobot rejected the API token (HTTP 401). The Nautobot source needs a valid token.",
    403: "The Nautobot API token lacks permission for this request (HTTP 403).",
}
_CODE_MESSAGES = {
    "timeout": "Nautobot did not answer in time.",
    "transport": "Could not reach Nautobot. Check that it is running.",
    "graphql_error": "Nautobot rejected the query.",
}


def failure_message(exc: BackendNautobotError) -> str:
    """A short, fixed sentence for a failed Nautobot call; never text from the response."""
    if exc.http_status in _STATUS_MESSAGES:
        return _STATUS_MESSAGES[exc.http_status]
    if exc.code in _CODE_MESSAGES:
        return _CODE_MESSAGES[exc.code]
    if isinstance(exc, NautobotAPIError) and exc.http_status:
        return f"Nautobot returned an error (HTTP {exc.http_status})."
    return "The Nautobot source is not usable (check its URL and token)."


class NautobotServiceClient(GraphQLClient):
    """The library's ``graphql`` transport on top of the app's ``NautobotService``."""

    def __init__(
        self, service: Any, credentials: NautobotCredentials, *, strict: bool = True
    ) -> None:
        """``strict`` (the default) raises on a response that carries GraphQL ``errors``.

        Right for answers shown to a person or a model: partial data must not read as "none".
        A caller that has always used the data next to a non-fatal error (a nested field the
        token may not read) passes ``strict=False``; the error count is logged, never the text.
        """
        self._service = service
        self._credentials = credentials
        self._strict = strict

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            result = await self._service.graphql_query(
                query, variables, self._credentials, strict=self._strict
            )
        except BackendNautobotError as exc:
            raise _query_error(exc) from exc
        errors = result.get("errors") if isinstance(result, dict) else None
        if errors:
            logger.warning(
                "Nautobot GraphQL answered with %d error(s); using its data",
                len(errors) if isinstance(errors, list) else 1,
            )
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict):
            raise QueryError("Nautobot sent an unexpected response.")
        return data

    async def rest_get(self, endpoint: str) -> Any:
        """GET below ``/api/`` (the free addresses of a prefix have no GraphQL equivalent).

        Only ever GET. The endpoint is built by the library from constants (a list endpoint, or
        the available-ips path of a validated UUID) plus URL-encoded filter values for a count;
        the service adds the base URL, token and SSRF policy.
        """
        try:
            return await self._service.rest_request(
                endpoint=endpoint, credentials=self._credentials, method="GET"
            )
        except BackendNautobotError as exc:
            # ``from None``: the service puts the whole endpoint, with its filter values (device
            # names, addresses, search text), into the exception message. ``_query_error`` logs
            # the code and status, which is all an operator needs; the chain would carry the URL
            # into logs and error trackers.
            raise _query_error(exc) from None


def _query_error(exc: BackendNautobotError) -> QueryError:
    logger.info("Nautobot query failed (%s)", exc.code or exc.http_status)
    return QueryError(failure_message(exc))

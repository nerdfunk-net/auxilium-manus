"""Nautobot reads for Ask the Net: the shared ``nautobot_read`` queries, run as the calling user.

``DbNautobotQueryReader`` checks ``sources.nautobot:read`` on every call, picks the first usable
Nautobot source (the same convention as the pages: "a page binds to the first source") and
returns a ``QueryContext`` for the library's query functions. The transport is the app's
``NautobotService`` (SSRF policy, TLS settings and credential handling stay in one place);
``NautobotServiceClient`` only maps its failures to short fixed messages, because the model must
never read raw upstream text.

The name vocabularies (roles, statuses, locations, ...) are cached per Nautobot instance and
token for the process, not per chat request: the toolbox is rebuilt on every request, so a cache
owned by it would never be hit.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Any

from nautobot_read.client import GraphQLClient
from nautobot_read.client import NautobotError as QueryError
from nautobot_read.context import QueryContext
from nautobot_read.vocabularies import VocabularyCache

import service_factory
from core.database import SessionLocal
from dependencies import nautobot_credentials_from_source_id
from services.auth.rbac_service import RBACService
from services.nautobot.common.exceptions import NautobotAPIError
from services.nautobot.common.exceptions import NautobotError as BackendNautobotError
from services.nautobot.credentials import NautobotCredentials
from services.settings.settings_service import SettingsService

logger = logging.getLogger(__name__)

# Instances kept in the vocabulary cache. A change of URL or token is a new key, so old entries
# only pile up when sources are edited; the oldest is dropped past this bound.
MAX_CACHED_INSTANCES = 8

_STATUS_MESSAGES = {
    401: "Nautobot rejected the API token (HTTP 401). The Nautobot source needs a valid token.",
    403: "The Nautobot API token lacks permission for this request (HTTP 403).",
}
_CODE_MESSAGES = {
    "timeout": "Nautobot did not answer in time.",
    "transport": "Could not reach Nautobot. Check that it is running.",
    "graphql_error": "Nautobot rejected the query.",
}


class NautobotAccessError(Exception):
    """The user may not read Nautobot data, or no usable Nautobot source is configured."""


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

    def __init__(self, service: Any, credentials: NautobotCredentials) -> None:
        self._service = service
        self._credentials = credentials

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            # strict: a response carrying GraphQL errors raises instead of being taken for
            # "no devices" (partial data must never read as an answer).
            result = await self._service.graphql_query(
                query, variables, self._credentials, strict=True
            )
        except BackendNautobotError as exc:
            raise _query_error(exc) from exc
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict):
            raise QueryError("Nautobot sent an unexpected response.")
        return data

    async def rest_get(self, endpoint: str) -> Any:
        """GET below ``/api/`` (the free addresses of a prefix have no GraphQL equivalent).

        Only ever GET, and the endpoint is built by the library from constants and a validated
        UUID; the service adds the base URL, token and SSRF policy.
        """
        try:
            return await self._service.rest_request(
                endpoint=endpoint, credentials=self._credentials, method="GET"
            )
        except BackendNautobotError as exc:
            raise _query_error(exc) from exc


def _query_error(exc: BackendNautobotError) -> QueryError:
    logger.info("AI assistant: Nautobot query failed (%s)", exc.code or exc.http_status)
    return QueryError(failure_message(exc))


_vocabularies: OrderedDict[str, VocabularyCache] = OrderedDict()


def vocabularies_for(scope: str, client: GraphQLClient) -> VocabularyCache:
    """The process-wide vocabulary cache of one Nautobot instance and token (``cache_scope``).

    The cached entry keeps the first client built for that scope; its credentials are the same
    by construction, because the scope is a digest of the URL and the token.
    """
    cache = _vocabularies.get(scope)
    if cache is None:
        cache = VocabularyCache(client)
        _vocabularies[scope] = cache
        while len(_vocabularies) > MAX_CACHED_INSTANCES:
            _vocabularies.popitem(last=False)
    else:
        _vocabularies.move_to_end(scope)
    return cache


class DbNautobotQueryReader:
    """Builds the query context for one user; ``context()`` raises ``NautobotAccessError``."""

    def __init__(self, user_id: int) -> None:
        self._user_id = user_id

    def _credentials(self) -> NautobotCredentials:
        with SessionLocal() as db:
            if not RBACService(db).has_permission(self._user_id, "sources.nautobot", "read"):
                raise NautobotAccessError
            sources = SettingsService(db).list_nautobot_source_summaries().sources
            for source in sources:
                try:
                    return nautobot_credentials_from_source_id(source.source_id, db)
                except Exception as exc:  # an unusable source must not hide a usable one
                    # The type says "bad config" from "database down" or "decryption failed";
                    # the message may carry credential text, so it stays out of this line.
                    logger.warning(
                        "AI assistant: Nautobot source %r unavailable (%s)",
                        source.source_id,
                        type(exc).__name__,
                    )
                    logger.debug("AI assistant: Nautobot source error detail", exc_info=True)
        if sources:
            logger.warning(
                "AI assistant: none of the %d Nautobot source(s) is usable", len(sources)
            )
        else:
            logger.info("AI assistant: no Nautobot source is configured")
        raise NautobotAccessError

    async def context(self) -> QueryContext:
        credentials = await asyncio.to_thread(self._credentials)
        client = NautobotServiceClient(service_factory.get_nautobot_app_service(), credentials)
        return QueryContext(
            client=client, vocabularies=vocabularies_for(credentials.cache_scope, client)
        )

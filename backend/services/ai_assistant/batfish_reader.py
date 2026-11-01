"""DB-backed ``BatfishReader`` for the Ask the Net Batfish tools (doc/AI_TOOL_CHAIN.md §10a, D1).

Wraps ``BatfishPreviewService`` -- the path the Template Editor already uses for ad-hoc reads --
and applies at least what the ``/sources/batfish`` query router applies:

* the ``sources.batfish:query`` permission (checked per call against the database),
* the router's per-user ``batfish-query`` rate-limit bucket (same name, same 30 per 60 s, so the
  assistant and the editor share one budget),
* the preview row cap (``MAX_PREVIEW_ROWS``) via ``PREVIEW_ROW_LIMIT``,
* the guard that a network must already exist, so a typo never creates a network on the
  coordinator (``assert_batfish_network_exists``, inside the preview service).

The model never supplies a host, port or path: the source is an admin-configured id and the
connection is resolved from it here. Every database call runs in a worker thread with its own
short session, so no session is held while a slow coordinator answers.

Errors are reduced to three types the tools understand; library text (hosts, ports, answers) is
logged, never passed on.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal, cast

import service_factory
from core.database import SessionLocal
from core.safe_http_errors import client_error_message
from models.batfish import (
    MAX_PREVIEW_ROWS,
    BatfishExtractFactsQueryRequest,
    BatfishGenericQueryRequest,
    BatfishInterfacePropertiesQueryRequest,
    BatfishQueryResponse,
    BatfishRoutesQueryRequest,
    BatfishTracerouteQueryRequest,
)
from services.ai_assistant.tools.batfish_tools import (
    BatfishAccessError,
    BatfishAnswer,
    BatfishInputError,
    BatfishUnavailableError,
)
from services.auth.login_rate_limiter import RateLimitExceededError
from services.auth.rbac_service import RBACService
from services.batfish.client import PREVIEW_ROW_LIMIT
from services.batfish.common.exceptions import BatfishAnswerFailedError, BatfishValidationError
from services.batfish.credentials import BatfishConnection
from services.batfish.preview_service import BatfishPreviewService
from services.batfish.query_helpers import assert_batfish_network_exists
from services.batfish.source_config_service import (
    BatfishSourceConfigService,
    BatfishSourceNotFoundError,
)

logger = logging.getLogger(__name__)

# Same bucket and budget as routers/sources/batfish/query.py: one budget per user for both.
RATE_LIMIT_BUCKET = "batfish-query"
RATE_LIMIT_ATTEMPTS = 30
RATE_LIMIT_WINDOW_SECONDS = 60

Kind = Literal["routes", "traceroute", "bgp_sessions", "interfaces", "facts"]


class _ResolvedSource:
    """Hands the preview service a connection that was already resolved in a worker thread."""

    def __init__(self, connection: BatfishConnection) -> None:
        self._connection = connection

    def resolve_connection(self, source_id: str) -> BatfishConnection:
        return self._connection


class DbBatfishReader:
    def __init__(self, user_id: int) -> None:
        self._user_id = user_id

    # -- discovery ---------------------------------------------------------------------------

    async def list_sources(self) -> list[str]:
        # A settings-table lookup: checked for permission, but not charged to the coordinator
        # budget (the tools call it before every query when the source is not named).
        await self._authorize(charge=False)
        return await asyncio.to_thread(self._list_sources)

    async def list_networks(self, source_id: str) -> list[str]:
        await self._authorize()
        connection = await self._connection(source_id)
        try:
            return await service_factory.get_batfish_app_service().list_networks(connection)
        except Exception as exc:
            raise self._unavailable("list networks", exc) from exc

    async def list_snapshots(self, source_id: str, network: str) -> list[dict[str, str]]:
        network = network.strip()
        await self._authorize()
        connection = await self._connection(source_id)
        batfish = service_factory.get_batfish_app_service()
        try:
            await assert_batfish_network_exists(batfish, connection, network)
            entries = await batfish.list_snapshots_with_metadata(
                connection, batfish_network=network
            )
        except ValueError as exc:
            raise BatfishInputError(client_error_message(exc)) from exc
        except Exception as exc:
            raise self._unavailable("list snapshots", exc) from exc
        return [
            {
                "name": str(entry.get("name", "")),
                "created": str((entry.get("metadata") or {}).get("creationTimestamp", "")),
            }
            for entry in entries
        ]

    # -- queries -----------------------------------------------------------------------------

    async def query(
        self,
        kind: Kind,
        source_id: str,
        network: str,
        snapshot: str | None,
        params: dict[str, Any],
    ) -> BatfishAnswer:
        # The existence guard and the call must see the same string.
        network = network.strip()
        snapshot = (snapshot or "").strip() or None
        await self._authorize()
        connection = await self._connection(source_id)
        batfish = service_factory.get_batfish_app_service()
        preview = BatfishPreviewService(
            source_config_service=cast(Any, _ResolvedSource(connection)), batfish_service=batfish
        )
        token = PREVIEW_ROW_LIMIT.set(MAX_PREVIEW_ROWS)
        try:
            response = await self._run(preview, kind, source_id, network, snapshot, params)
        except BatfishInputError:
            raise
        except BatfishAnswerFailedError as exc:
            logger.info("Batfish could not answer a %s question: %s", kind, exc)
            raise BatfishInputError(
                "Batfish could not answer: a device, interface or location in the request does "
                "not exist in this snapshot. Check the names with get_interface_properties or "
                "get_routes."
            ) from exc
        except (ValueError, BatfishValidationError) as exc:
            raise BatfishInputError(client_error_message(exc)) from exc
        except Exception as exc:
            raise self._unavailable(f"{kind} query", exc) from exc
        finally:
            PREVIEW_ROW_LIMIT.reset(token)
        created = await self._snapshot_created(connection, network, response.snapshot)
        rows = response.rows
        if kind == "facts":
            # extract_facts answers per node, not as rows: one row per node keeps the tools uniform.
            rows = [
                {"Node": node, "Facts": facts}
                for node, facts in sorted((response.facts_by_node or {}).items())
            ]
        return BatfishAnswer(
            rows=rows,
            snapshot=response.snapshot,
            snapshot_created=created,
            truncated=response.truncated,
        )

    async def _run(
        self,
        preview: BatfishPreviewService,
        kind: str,
        source_id: str,
        network: str,
        snapshot: str | None,
        params: dict[str, Any],
    ) -> BatfishQueryResponse:
        if kind == "routes":
            request = BatfishRoutesQueryRequest(network=network, snapshot=snapshot, **params)
            return await preview.run_routes(source_id, request)
        if kind == "traceroute":
            trace = BatfishTracerouteQueryRequest(network=network, snapshot=snapshot, **params)
            return await preview.run_traceroute(source_id, trace)
        if kind == "bgp_sessions":
            generic = BatfishGenericQueryRequest(
                network=network,
                snapshot=snapshot,
                question="bgpSessionStatus",
                params={"nodes": params.get("nodes")},
            )
            return await preview.run_generic(source_id, generic)
        if kind == "interfaces":
            iface = BatfishInterfacePropertiesQueryRequest(
                network=network, snapshot=snapshot, **params
            )
            return await preview.run_interface_rows(source_id, iface)
        if kind == "facts":
            nodes_filter = (params.get("nodes") or "").strip() or "/.*/"
            facts = BatfishExtractFactsQueryRequest(
                network=network, snapshot=snapshot, nodes_filter=nodes_filter
            )
            return await preview.run_extract_facts(source_id, facts)
        raise BatfishInputError(f"Unknown Batfish query '{kind}'.")

    # -- helpers -----------------------------------------------------------------------------

    async def _authorize(self, *, charge: bool = True) -> None:
        await asyncio.to_thread(self._check_permission_and_limit, charge)

    def _check_permission_and_limit(self, charge: bool) -> None:
        with SessionLocal() as db:
            allowed = RBACService(db).has_permission(self._user_id, "sources.batfish", "query")
        if not allowed:
            raise BatfishAccessError
        if not charge:
            return
        limiter = service_factory.build_user_rate_limiter(
            RATE_LIMIT_BUCKET, RATE_LIMIT_ATTEMPTS, RATE_LIMIT_WINDOW_SECONDS
        )
        try:
            limiter.check(f"{RATE_LIMIT_BUCKET}:{self._user_id}")
        except RateLimitExceededError as exc:
            raise BatfishInputError(
                "Too many Batfish queries in the last minute; wait a minute and try again."
            ) from exc

    def _list_sources(self) -> list[str]:
        with SessionLocal() as db:
            return [str(s["source_id"]) for s in BatfishSourceConfigService(db).list_sources()]

    async def _connection(self, source_id: str) -> BatfishConnection:
        return await asyncio.to_thread(self._resolve_connection, source_id)

    def _resolve_connection(self, source_id: str) -> BatfishConnection:
        with SessionLocal() as db:
            try:
                return BatfishSourceConfigService(db).resolve_connection(source_id)
            except BatfishSourceNotFoundError as exc:
                raise BatfishInputError(f"Unknown Batfish source '{source_id}'.") from exc
            except BatfishValidationError as exc:
                raise BatfishInputError(client_error_message(exc)) from exc

    async def _snapshot_created(
        self, connection: BatfishConnection, network: str, snapshot: str
    ) -> str | None:
        """Creation time of the snapshot used, so the answer can say how old it is. Best effort."""
        try:
            entries = await service_factory.get_batfish_app_service().list_snapshots_with_metadata(
                connection, batfish_network=network
            )
        except Exception as exc:
            logger.debug("Could not look up the creation time of snapshot %s: %s", snapshot, exc)
            return None
        for entry in entries:
            if entry.get("name") == snapshot:
                created = (entry.get("metadata") or {}).get("creationTimestamp")
                return str(created) if created else None
        return None

    @staticmethod
    def _unavailable(action: str, exc: Exception) -> BatfishUnavailableError:
        logger.error("Batfish %s failed: %s", action, exc)
        return BatfishUnavailableError()

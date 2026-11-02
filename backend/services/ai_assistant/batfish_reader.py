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
from typing import Any, cast

import service_factory
from core.database import SessionLocal
from core.safe_http_errors import client_error_message
from models.batfish import (
    MAX_PREVIEW_ROWS,
    BatfishCompareFiltersQueryRequest,
    BatfishDifferentialReachabilityQueryRequest,
    BatfishExtractFactsQueryRequest,
    BatfishGenericQueryRequest,
    BatfishInterfacePropertiesQueryRequest,
    BatfishNodePropertiesQueryRequest,
    BatfishQueryResponse,
    BatfishReachabilityQueryRequest,
    BatfishRoutesQueryRequest,
    BatfishTestFiltersQueryRequest,
    BatfishTracerouteQueryRequest,
)
from services.ai_assistant.node_names import NodeNameCache, resolve_node_names
from services.ai_assistant.tools.batfish_shaping import FACT_KEYS, facts_from_node_properties
from services.ai_assistant.tools.batfish_tools import (
    BatfishAccessError,
    BatfishAnswer,
    BatfishInputError,
    BatfishUnavailableError,
    DeviceListing,
    NodeListing,
    QueryKind,
    SnapshotDiagnostics,
)
from services.auth.login_rate_limiter import RateLimitExceededError
from services.auth.rbac_service import RBACService
from services.batfish.client import PREVIEW_ROW_LIMIT
from services.batfish.common.exceptions import (
    BatfishAnswerFailedError,
    BatfishAPIError,
    BatfishValidationError,
    FilterNotFoundError,
)
from services.batfish.credentials import BatfishConnection
from services.batfish.preview_service import BatfishPreviewService
from services.batfish.query_helpers import (
    assert_batfish_network_exists,
    query_node_properties,
    resolve_latest_snapshot_name,
)
from services.batfish.source_config_service import (
    BatfishSourceConfigService,
    BatfishSourceNotFoundError,
)

logger = logging.getLogger(__name__)

# Same bucket and budget as routers/sources/batfish/query.py: one budget per user for both.
RATE_LIMIT_BUCKET = "batfish-query"
RATE_LIMIT_ATTEMPTS = 30
RATE_LIMIT_WINDOW_SECONDS = 60

Kind = QueryKind

# Query parameters that carry device names: a comma-separated list, or one name each.
_NODE_LIST_PARAMS = ("nodes",)
_NODE_SINGLE_PARAMS = ("node", "start_node", "end_node")
# Node names per snapshot, so the lookup is not repeated for every tool call of a question.
NODE_CACHE = NodeNameCache()
MAX_LISTED_NODES = 10


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
        # Names the user or Nautobot wrote (``LAB.local.zz``) become the Batfish node names
        # (``lab``) before anything reaches the coordinator.
        snapshot, params, nodes_resolved = await self._resolve_device_names(
            batfish, connection, network, snapshot, params
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
        reference_created = (
            await self._snapshot_created(connection, network, response.reference_snapshot)
            if response.reference_snapshot
            else None
        )
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
            reference_snapshot=response.reference_snapshot,
            reference_created=reference_created,
            truncated=response.truncated,
            nodes_resolved=nodes_resolved,
        )

    async def snapshot_devices(
        self,
        source_id: str,
        network: str,
        snapshot: str | None,
        nodes: list[str],
        with_ips: bool,
    ) -> DeviceListing:
        """The devices of a snapshot with their IPs: one permission check and one rate-limit
        charge for the two questions."""
        network = network.strip()
        snapshot = (snapshot or "").strip() or None
        await self._authorize()
        connection = await self._connection(source_id)
        batfish = service_factory.get_batfish_app_service()
        preview = BatfishPreviewService(
            source_config_service=cast(Any, _ResolvedSource(connection)), batfish_service=batfish
        )
        snapshot, params, nodes_resolved = await self._resolve_device_names(
            batfish, connection, network, snapshot, {"nodes": ",".join(nodes) or None}
        )
        token = PREVIEW_ROW_LIMIT.set(MAX_PREVIEW_ROWS)
        try:
            result = await preview.run_snapshot_devices(
                source_id, network, snapshot, params.get("nodes"), with_ips=with_ips
            )
        except (ValueError, BatfishValidationError) as exc:
            raise BatfishInputError(client_error_message(exc)) from exc
        except Exception as exc:
            raise self._unavailable("list devices", exc) from exc
        finally:
            PREVIEW_ROW_LIMIT.reset(token)
        return DeviceListing(
            snapshot=result.snapshot,
            snapshot_created=await self._snapshot_created(connection, network, result.snapshot),
            node_rows=result.node_rows,
            ip_rows=result.ip_rows,
            unavailable=result.unavailable,
            truncated_sections=result.truncated_sections,
            nodes_resolved=nodes_resolved,
        )

    async def node_names(self, source_id: str, network: str, snapshot: str | None) -> NodeListing:
        """The device names of a snapshot, for matching a name from Nautobot or the user."""
        network = network.strip()
        snapshot = (snapshot or "").strip() or None
        await self._authorize()
        connection = await self._connection(source_id)
        batfish = service_factory.get_batfish_app_service()
        try:
            resolved, names = await self._node_names(batfish, connection, network, snapshot)
        except (ValueError, BatfishValidationError) as exc:
            raise BatfishInputError(client_error_message(exc)) from exc
        except Exception as exc:
            raise self._unavailable("list nodes", exc) from exc
        return NodeListing(
            snapshot=resolved,
            snapshot_created=await self._snapshot_created(connection, network, resolved),
            names=names,
        )

    async def _resolve_device_names(
        self,
        batfish: Any,
        connection: BatfishConnection,
        network: str,
        snapshot: str | None,
        params: dict[str, Any],
    ) -> tuple[str | None, dict[str, Any], dict[str, str]]:
        """Rewrite the device names in ``params`` to the node names of the snapshot.

        Returns ``(snapshot, params, rewritten)``. Nothing is looked up when no name is given.
        When the node list cannot be read the query goes ahead unchanged (it reports the real
        problem itself). A name that matches no node, or several, is an input error naming the
        candidates: it is never guessed.
        """
        requested = _requested_names(params)
        if not requested:
            return snapshot, params, {}
        try:
            resolved_snapshot, nodes = await self._node_names(
                batfish, connection, network, snapshot
            )
        except Exception as exc:
            logger.info("Could not list the nodes of %s/%s: %s", network, snapshot, exc)
            return snapshot, _lowered(params, requested), {}
        if not nodes:
            return resolved_snapshot, _lowered(params, requested), {}
        outcome = resolve_node_names(requested, nodes)
        if outcome.ambiguous or outcome.unknown:
            raise BatfishInputError(_name_problem(outcome, nodes, resolved_snapshot))
        return resolved_snapshot, _with_node_names(params, outcome.resolved), outcome.changed

    async def _node_names(
        self, batfish: Any, connection: BatfishConnection, network: str, snapshot: str | None
    ) -> tuple[str, tuple[str, ...]]:
        # A typo must not create a network, and the snapshot must be the one the query will use.
        await assert_batfish_network_exists(batfish, connection, network)
        resolved = snapshot or await resolve_latest_snapshot_name(batfish, connection, network)
        key = (connection.host, connection.port, network, resolved)
        cached = NODE_CACHE.get(key)
        if cached is not None:
            return resolved, cached
        rows = await query_node_properties(
            batfish,
            connection,
            batfish_network=network,
            snapshot=resolved,
            properties="Hostname",
        )
        names = tuple(sorted({str(row["Node"]) for row in rows if row.get("Node")}))
        NODE_CACHE.put(key, names)
        return resolved, names

    async def snapshot_diagnostics(
        self, source_id: str, network: str, snapshot: str | None
    ) -> SnapshotDiagnostics:
        """What Batfish reported while reading a snapshot: one permission check and one
        rate-limit charge for the three parse questions."""
        # The existence guard and the calls must see the same string.
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
            result = await preview.run_parse_diagnostics(source_id, network, snapshot)
        except (ValueError, BatfishValidationError) as exc:
            raise BatfishInputError(client_error_message(exc)) from exc
        except Exception as exc:
            raise self._unavailable("parse diagnostics", exc) from exc
        finally:
            PREVIEW_ROW_LIMIT.reset(token)
        return SnapshotDiagnostics(
            snapshot=result.snapshot,
            snapshot_created=await self._snapshot_created(connection, network, result.snapshot),
            file_status=result.file_status,
            warnings=result.warnings,
            issues=result.issues,
            unavailable=result.unavailable,
            truncated=result.truncated,
            truncated_sections=result.truncated_sections,
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
        if kind == "reachability":
            reach = BatfishReachabilityQueryRequest(network=network, snapshot=snapshot, **params)
            return await preview.run_reachability(source_id, reach)
        if kind == "compare_filters":
            cmp_request = BatfishCompareFiltersQueryRequest(
                network=network, snapshot=snapshot, **params
            )
            return await preview.run_compare_filters(source_id, cmp_request)
        if kind == "differential_reachability":
            diff_request = BatfishDifferentialReachabilityQueryRequest(
                network=network, snapshot=snapshot, **params
            )
            return await preview.run_differential_reachability(source_id, diff_request)
        if kind == "acl":
            return await self._run_acl(preview, source_id, network, snapshot, params)
        if kind == "ip_owners":
            return await self._run_ip_owners(preview, source_id, network, snapshot, params)
        if kind == "facts":
            return await self._run_facts(preview, source_id, network, snapshot, params)
        raise BatfishInputError(f"Unknown Batfish query '{kind}'.")

    @staticmethod
    async def _run_facts(
        preview: BatfishPreviewService,
        source_id: str,
        network: str,
        snapshot: str | None,
        params: dict[str, Any],
    ) -> BatfishQueryResponse:
        """Device facts from one ``nodeProperties`` question restricted to the requested columns.

        ``extractFacts`` runs seven questions with every property for every node; every fact the
        tool offers is a plain ``nodeProperties`` column. If this question is rejected (the column
        names were not checked against a live coordinator) the slow, known path answers instead.
        """
        keys = _fact_keys(params.get("facts"))
        request = BatfishNodePropertiesQueryRequest(
            network=network,
            snapshot=snapshot,
            nodes=(params.get("nodes") or "").strip() or None,
            properties=", ".join(keys),
        )
        try:
            response = await preview.run_node_properties(source_id, request)
        except BatfishAnswerFailedError:
            raise  # a device that is not there: the slow path would say the same
        except BatfishAPIError as exc:
            logger.warning("nodeProperties for device facts failed (%s); falling back", exc)
            fallback = BatfishExtractFactsQueryRequest(
                network=network,
                snapshot=snapshot,
                nodes_filter=(params.get("nodes") or "").strip() or "/.*/",
            )
            return await preview.run_extract_facts(source_id, fallback)
        return response.model_copy(
            update={"facts_by_node": facts_from_node_properties(response.facts_by_node or {})}
        )

    @staticmethod
    async def _run_ip_owners(
        preview: BatfishPreviewService,
        source_id: str,
        network: str,
        snapshot: str | None,
        params: dict[str, Any],
    ) -> BatfishQueryResponse:
        """``ipOwners`` has no node parameter: the preview service applies the node filter to the
        rows before the response cap."""
        return await preview.run_ip_owners(
            source_id,
            network,
            snapshot,
            params.get("ips") or None,
            bool(params.get("duplicates_only")),
            params.get("nodes") or None,
        )

    @staticmethod
    async def _run_acl(
        preview: BatfishPreviewService,
        source_id: str,
        network: str,
        snapshot: str | None,
        params: dict[str, Any],
    ) -> BatfishQueryResponse:
        request = BatfishTestFiltersQueryRequest(network=network, snapshot=snapshot, **params)
        try:
            return await preview.run_test_filters(source_id, request)
        except FilterNotFoundError as exc:
            # testFilters returns nothing when the device or filter name matches nothing; any
            # other RuntimeError is not a bad name and takes the 'unavailable' path.
            logger.info("testFilters matched nothing: %s", exc)
            raise BatfishInputError(
                "Batfish found no filter with that name on that device in this snapshot. Get the "
                "name from get_interface_properties (Incoming_Filter_Name / Outgoing_Filter_Name)."
            ) from exc

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


def _fact_keys(value: Any) -> list[str]:
    """The facts to fetch: only names the tool offers (never key material), default all of them."""
    requested = _split(value)
    unknown = [key for key in requested if key not in FACT_KEYS]
    if unknown:
        raise BatfishInputError(f"Unknown fact: {', '.join(unknown)}.")
    return requested or list(FACT_KEYS)


def _split(value: Any) -> list[str]:
    return [part.strip() for part in str(value).split(",") if part.strip()] if value else []


def _requested_names(params: dict[str, Any]) -> list[str]:
    names = [n for key in _NODE_LIST_PARAMS for n in _split(params.get(key))]
    names += [n for key in _NODE_SINGLE_PARAMS for n in _split(params.get(key))]
    return list(dict.fromkeys(names))


def _with_node_names(params: dict[str, Any], resolved: dict[str, str]) -> dict[str, Any]:
    """A copy of ``params`` with every device name replaced by its node name."""
    updated = dict(params)
    for key in (*_NODE_LIST_PARAMS, *_NODE_SINGLE_PARAMS):
        names = _split(params.get(key))
        if names:
            updated[key] = ",".join(resolved.get(name, name) for name in names)
    return updated


def _lowered(params: dict[str, Any], requested: list[str]) -> dict[str, Any]:
    """Without a node list the best guess is how Batfish spells hostnames: lower case."""
    return _with_node_names(params, {name: name.lower() for name in requested})


def _name_problem(outcome: Any, nodes: tuple[str, ...], snapshot: str) -> str:
    parts = []
    for name, candidates in outcome.ambiguous.items():
        parts.append(
            f"'{name}' matches several devices in snapshot '{snapshot}': "
            f"{', '.join(candidates)}. Ask the user which one, then use the full name."
        )
    for name, close in outcome.unknown.items():
        hint = (
            f"Close names, not necessarily the same device (ask the user before using one): "
            f"{', '.join(close)}."
            if close
            else f"Devices in this snapshot: {', '.join(nodes[:MAX_LISTED_NODES])}"
            f"{' ...' if len(nodes) > MAX_LISTED_NODES else ''}."
        )
        parts.append(f"No device '{name}' in snapshot '{snapshot}'. {hint}")
    parts.append(
        "Batfish names a device after the hostname in its config (lower case, usually without "
        "the domain)."
    )
    return " ".join(parts)

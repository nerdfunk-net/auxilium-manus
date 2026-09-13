"""Batfish editor-preview operations -- ad-hoc routes/reachability/testFilters
queries run directly against a configured source + network(+snapshot), with
no WorkflowRun/WorkflowContext involved. Mirrors
``services.network.netmiko.preview_service.NetmikoPreviewService``'s role:
the Template Editor's Options modal calls this to preview a Batfish answer
and turn it into a template variable, the same way the Netmiko preview
service lets it preview a device's parsed config.

Reuses the exact same pybatfish call shapes as the batfish-routing-table/
batfish-path-check/batfish-acl-check workflow-step executors (via the shared
``services.batfish.query_helpers`` helpers) so a preview here behaves
identically to what the real workflow step would produce.
"""

from __future__ import annotations

from typing import Any

from models.batfish import (
    BatfishQueryResponse,
    BatfishReachabilityQueryRequest,
    BatfishRoutesQueryRequest,
    BatfishTestFiltersQueryRequest,
)
from services.batfish.client import BatfishService
from services.batfish.common.exceptions import BatfishValidationError
from services.batfish.credentials import BatfishConnection
from services.batfish.query_helpers import build_batfish_headers, resolve_latest_snapshot_name
from services.batfish.source_config_service import BatfishSourceConfigService


def _or_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


class BatfishPreviewService:
    def __init__(
        self,
        source_config_service: BatfishSourceConfigService,
        batfish_service: BatfishService,
    ) -> None:
        self._source_config_service = source_config_service
        self._batfish = batfish_service

    async def _resolve(
        self, source_id: str, network: str, snapshot: str | None
    ) -> tuple[BatfishConnection, str]:
        clean_network = network.strip()
        if not clean_network:
            raise BatfishValidationError("network is required")
        connection = self._source_config_service.resolve_connection(source_id)
        resolved_snapshot = (snapshot or "").strip()
        if not resolved_snapshot:
            resolved_snapshot = await resolve_latest_snapshot_name(
                self._batfish, connection, clean_network
            )
        return connection, resolved_snapshot

    async def run_routes(
        self, source_id: str, request: BatfishRoutesQueryRequest
    ) -> BatfishQueryResponse:
        connection, snapshot = await self._resolve(source_id, request.network, request.snapshot)
        rows = await self._batfish.routes(
            connection,
            batfish_network=request.network,
            snapshot=snapshot,
            nodes=_or_none(request.nodes),
            network=_or_none(request.network_prefix),
            prefixMatchType=_or_none(request.prefix_match_type),
            protocols=_or_none(request.protocols),
            vrfs=_or_none(request.vrfs),
            rib=_or_none(request.rib),
        )
        return BatfishQueryResponse(
            success=True,
            question="routes",
            network=request.network,
            snapshot=snapshot,
            rows=rows,
        )

    async def run_reachability(
        self, source_id: str, request: BatfishReachabilityQueryRequest
    ) -> BatfishQueryResponse:
        start_node = request.start_node.strip()
        if not start_node:
            raise BatfishValidationError("start_node is required")

        connection, snapshot = await self._resolve(source_id, request.network, request.snapshot)

        path_constraints: dict[str, Any] = {"startLocation": start_node}
        end_node = (request.end_node or "").strip()
        if end_node:
            path_constraints["endLocation"] = end_node

        headers = build_batfish_headers(
            dst_ips=request.dst_ips,
            src_ips=request.src_ips,
            applications=request.applications,
            ip_protocols=request.ip_protocols,
        )

        rows = await self._batfish.reachability(
            connection,
            batfish_network=request.network,
            snapshot=snapshot,
            pathConstraints=path_constraints,
            headers=headers or None,
            maxTraces=request.max_traces,
            invertSearch=request.invert_search,
            ignoreFilters=request.ignore_filters,
        )
        return BatfishQueryResponse(
            success=True,
            question="reachability",
            network=request.network,
            snapshot=snapshot,
            rows=rows,
            reachable=len(rows) > 0,
        )

    async def run_test_filters(
        self, source_id: str, request: BatfishTestFiltersQueryRequest
    ) -> BatfishQueryResponse:
        node = request.node.strip()
        filter_name = request.filter_name.strip()
        dst_ips = request.dst_ips.strip()
        if not node:
            raise BatfishValidationError("node is required")
        if not filter_name:
            raise BatfishValidationError("filter_name is required")
        if not dst_ips:
            raise BatfishValidationError("dst_ips is required")

        connection, snapshot = await self._resolve(source_id, request.network, request.snapshot)
        headers = build_batfish_headers(
            dst_ips=dst_ips,
            src_ips=request.src_ips,
            applications=request.applications,
            ip_protocols=request.ip_protocols,
        )
        start_location = (request.start_location or "").strip() or None

        rows = await self._batfish.test_filters(
            connection,
            batfish_network=request.network,
            snapshot=snapshot,
            nodes=node,
            filters=filter_name,
            headers=headers,
            startLocation=start_location,
        )
        if not rows:
            raise BatfishValidationError(
                "No result returned -- check that node/filter_name match the snapshot"
            )

        action = str(rows[0].get("Action", "")).strip().upper()
        return BatfishQueryResponse(
            success=True,
            question="testFilters",
            network=request.network,
            snapshot=snapshot,
            rows=rows,
            action=action,
        )

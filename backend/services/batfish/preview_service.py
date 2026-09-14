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

from models.batfish import (
    BatfishQueryResponse,
    BatfishReachabilityQueryRequest,
    BatfishRoutesQueryRequest,
    BatfishTestFiltersQueryRequest,
)
from services.batfish.client import BatfishService
from services.batfish.common.exceptions import BatfishValidationError
from services.batfish.credentials import BatfishConnection
from services.batfish.query_helpers import (
    assert_batfish_network_exists,
    query_reachability,
    query_routes,
    query_test_filters,
    require_field,
    resolve_latest_snapshot_name,
)
from services.batfish.source_config_service import BatfishSourceConfigService


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
        # Must happen before anything below touches
        # BatfishService._get_session() for this network -- see
        # assert_batfish_network_exists' docstring for why.
        await assert_batfish_network_exists(self._batfish, connection, clean_network)
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
        rows = await query_routes(
            self._batfish,
            connection,
            batfish_network=request.network,
            snapshot=snapshot,
            nodes=request.nodes,
            network_prefix=request.network_prefix,
            prefix_match_type=request.prefix_match_type,
            protocols=request.protocols,
            vrfs=request.vrfs,
            rib=request.rib,
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
        start_node = require_field(request.start_node, "start_node")
        connection, snapshot = await self._resolve(source_id, request.network, request.snapshot)

        rows, reachable = await query_reachability(
            self._batfish,
            connection,
            batfish_network=request.network,
            snapshot=snapshot,
            start_node=start_node,
            end_node=request.end_node,
            dst_ips=request.dst_ips,
            src_ips=request.src_ips,
            applications=request.applications,
            ip_protocols=request.ip_protocols,
            max_traces=request.max_traces,
            invert_search=request.invert_search,
            ignore_filters=request.ignore_filters,
        )
        return BatfishQueryResponse(
            success=True,
            question="reachability",
            network=request.network,
            snapshot=snapshot,
            rows=rows,
            reachable=reachable,
        )

    async def run_test_filters(
        self, source_id: str, request: BatfishTestFiltersQueryRequest
    ) -> BatfishQueryResponse:
        node = require_field(request.node, "node")
        filter_name = require_field(request.filter_name, "filter_name")
        dst_ips = require_field(request.dst_ips, "dst_ips")

        connection, snapshot = await self._resolve(source_id, request.network, request.snapshot)
        rows, action = await query_test_filters(
            self._batfish,
            connection,
            batfish_network=request.network,
            snapshot=snapshot,
            node=node,
            filter_name=filter_name,
            dst_ips=dst_ips,
            src_ips=request.src_ips,
            applications=request.applications,
            ip_protocols=request.ip_protocols,
            start_location=request.start_location,
        )
        return BatfishQueryResponse(
            success=True,
            question="testFilters",
            network=request.network,
            snapshot=snapshot,
            rows=rows,
            action=action,
        )

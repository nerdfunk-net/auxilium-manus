"""Batfish editor-preview operations -- ad-hoc queries run directly against a
configured source + network(+snapshot), with no WorkflowRun/WorkflowContext
involved. Mirrors ``services.network.netmiko.preview_service.NetmikoPreviewService``'s
role: the Template Editor's Options modal calls this to preview a Batfish
answer and turn it into a template variable, the same way the Netmiko
preview service lets it preview a device's parsed config.

Two response shapes, matching two different runtime realities (see
doc/BATFISH_INTEGRATION.md "Template Editor integration" for the full
writeup):

- ``run_routes``/``run_reachability``/``run_test_filters``/``run_generic``
  reuse the exact same pybatfish call shapes as the batfish-routing-table/
  batfish-path-check/batfish-acl-check workflow-step executors (via the
  shared ``services.batfish.query_helpers`` helpers) and return a flat
  ``rows`` table -- these 4 steps never populate any device's ``parsed`` at
  real workflow runtime, so their preview is genuinely standalone (see the
  ``batfish`` template variable's own "preview-only" documentation).
- ``run_extract_facts``/``run_ospf_facts``/``run_bgp_facts``/
  ``run_node_properties``/``run_interface_properties`` return
  ``facts_by_node`` -- reusing ``services.batfish.facts_specs``'s merge/group
  helpers (shared with the real workflow steps' ``devices`` outcome) so the
  preview is byte-for-byte what ``device.parsed[output_key]["parsed"]``
  would hold for one node at real runtime.
"""

from __future__ import annotations

from typing import Any

from models.batfish import (
    BatfishBgpFactsQueryRequest,
    BatfishExtractFactsQueryRequest,
    BatfishGenericQueryRequest,
    BatfishInterfacePropertiesQueryRequest,
    BatfishNodePropertiesQueryRequest,
    BatfishOspfFactsQueryRequest,
    BatfishQueryResponse,
    BatfishReachabilityQueryRequest,
    BatfishRoutesQueryRequest,
    BatfishTestFiltersQueryRequest,
)
from services.batfish.bgp_facts import BGP_QUESTION_SPECS
from services.batfish.client import BatfishService
from services.batfish.common.exceptions import BatfishValidationError
from services.batfish.credentials import BatfishConnection
from services.batfish.facts_specs import (
    CombinedQuestionSpec,
    facts_by_node_for_property,
    merge_facts_by_node,
)
from services.batfish.interface_properties_spec import INTERFACE_PROPERTIES_SPEC
from services.batfish.node_properties_spec import NODE_PROPERTIES_SPEC
from services.batfish.ospf_facts import OSPF_QUESTION_SPECS
from services.batfish.query_helpers import (
    assert_batfish_network_exists,
    query_bgp_edges,
    query_bgp_peer_configuration,
    query_bgp_process_configuration,
    query_bgp_session_status,
    query_generic,
    query_interface_properties,
    query_node_properties,
    query_ospf_area_configuration,
    query_ospf_edges,
    query_ospf_interface_configuration,
    query_ospf_process_configuration,
    query_reachability,
    query_routes,
    query_test_filters,
    require_field,
    resolve_latest_snapshot_name,
)
from services.batfish.source_config_service import BatfishSourceConfigService

# key -> (query_helpers function, CombinedQuestionSpec) for each OSPF/BGP
# sub-question, keyed the same way as their `include_<key>` request fields.
_OSPF_QUERY_FNS = {
    "process": query_ospf_process_configuration,
    "areas": query_ospf_area_configuration,
    "interfaces": query_ospf_interface_configuration,
    "edges": query_ospf_edges,
}
_BGP_QUERY_FNS = {
    "process": query_bgp_process_configuration,
    "peers": query_bgp_peer_configuration,
    "sessions": query_bgp_session_status,
    "edges": query_bgp_edges,
}


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

    async def run_generic(
        self, source_id: str, request: BatfishGenericQueryRequest
    ) -> BatfishQueryResponse:
        question = require_field(request.question, "question")
        connection, snapshot = await self._resolve(source_id, request.network, request.snapshot)
        rows = await query_generic(
            self._batfish,
            connection,
            batfish_network=request.network,
            snapshot=snapshot,
            question_name=question,
            params=request.params,
        )
        return BatfishQueryResponse(
            success=True,
            question=question,
            network=request.network,
            snapshot=snapshot,
            rows=rows,
        )

    async def run_extract_facts(
        self, source_id: str, request: BatfishExtractFactsQueryRequest
    ) -> BatfishQueryResponse:
        connection, snapshot = await self._resolve(source_id, request.network, request.snapshot)
        nodes_filter = (request.nodes_filter or "").strip() or "/.*/"
        facts = await self._batfish.extract_facts(
            connection,
            batfish_network=request.network,
            nodes=nodes_filter,
            snapshot=snapshot,
        )
        raw_nodes = facts.get("nodes") if isinstance(facts, dict) else None
        facts_by_node = raw_nodes if isinstance(raw_nodes, dict) else {}
        return BatfishQueryResponse(
            success=True,
            question="extractFacts",
            network=request.network,
            snapshot=snapshot,
            rows=[],
            facts_by_node=facts_by_node,
        )

    async def _run_combined_facts(
        self,
        source_id: str,
        *,
        network: str,
        snapshot_in: str | None,
        nodes: str | None,
        specs: dict[str, CombinedQuestionSpec],
        query_fns: dict[str, Any],
        enabled_keys: list[str],
        question_name: str,
    ) -> BatfishQueryResponse:
        if not enabled_keys:
            raise ValueError(
                f"{question_name}: at least one question must be enabled (include_*)"
            )
        connection, snapshot = await self._resolve(source_id, network, snapshot_in)

        rows_by_question: dict[str, list[dict[str, Any]]] = {}
        for key in enabled_keys:
            rows_by_question[key] = await query_fns[key](
                self._batfish,
                connection,
                batfish_network=network,
                snapshot=snapshot,
                nodes=nodes,
            )

        facts_by_node = merge_facts_by_node(specs, rows_by_question)
        return BatfishQueryResponse(
            success=True,
            question=question_name,
            network=network,
            snapshot=snapshot,
            rows=[],
            facts_by_node=facts_by_node,
        )

    async def run_ospf_facts(
        self, source_id: str, request: BatfishOspfFactsQueryRequest
    ) -> BatfishQueryResponse:
        enabled_keys = [
            key
            for key, toggle in (
                ("process", request.include_process),
                ("areas", request.include_areas),
                ("interfaces", request.include_interfaces),
                ("edges", request.include_edges),
            )
            if toggle
        ]
        return await self._run_combined_facts(
            source_id,
            network=request.network,
            snapshot_in=request.snapshot,
            nodes=request.nodes,
            specs=OSPF_QUESTION_SPECS,
            query_fns=_OSPF_QUERY_FNS,
            enabled_keys=enabled_keys,
            question_name="ospfFacts",
        )

    async def run_bgp_facts(
        self, source_id: str, request: BatfishBgpFactsQueryRequest
    ) -> BatfishQueryResponse:
        enabled_keys = [
            key
            for key, toggle in (
                ("process", request.include_process),
                ("peers", request.include_peers),
                ("sessions", request.include_sessions),
                ("edges", request.include_edges),
            )
            if toggle
        ]
        return await self._run_combined_facts(
            source_id,
            network=request.network,
            snapshot_in=request.snapshot,
            nodes=request.nodes,
            specs=BGP_QUESTION_SPECS,
            query_fns=_BGP_QUERY_FNS,
            enabled_keys=enabled_keys,
            question_name="bgpFacts",
        )

    async def run_node_properties(
        self, source_id: str, request: BatfishNodePropertiesQueryRequest
    ) -> BatfishQueryResponse:
        connection, snapshot = await self._resolve(source_id, request.network, request.snapshot)
        rows = await query_node_properties(
            self._batfish,
            connection,
            batfish_network=request.network,
            snapshot=snapshot,
            nodes=request.nodes,
            properties=request.properties,
        )
        facts_by_node = facts_by_node_for_property(NODE_PROPERTIES_SPEC, rows)
        return BatfishQueryResponse(
            success=True,
            question=NODE_PROPERTIES_SPEC.question_label,
            network=request.network,
            snapshot=snapshot,
            rows=[],
            facts_by_node=facts_by_node,
        )

    async def run_interface_properties(
        self, source_id: str, request: BatfishInterfacePropertiesQueryRequest
    ) -> BatfishQueryResponse:
        connection, snapshot = await self._resolve(source_id, request.network, request.snapshot)
        rows = await query_interface_properties(
            self._batfish,
            connection,
            batfish_network=request.network,
            snapshot=snapshot,
            nodes=request.nodes,
            interfaces=request.interfaces,
            properties=request.properties,
        )
        facts_by_node = facts_by_node_for_property(INTERFACE_PROPERTIES_SPEC, rows)
        return BatfishQueryResponse(
            success=True,
            question=INTERFACE_PROPERTIES_SPEC.question_label,
            network=request.network,
            snapshot=snapshot,
            rows=[],
            facts_by_node=facts_by_node,
        )

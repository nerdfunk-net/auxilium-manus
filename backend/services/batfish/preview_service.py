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

import logging
from dataclasses import dataclass, field
from typing import Any

from models.batfish import (
    MAX_PREVIEW_ROWS,
    BatfishBgpFactsQueryRequest,
    BatfishCompareFiltersQueryRequest,
    BatfishDifferentialReachabilityQueryRequest,
    BatfishExtractFactsQueryRequest,
    BatfishGenericQueryRequest,
    BatfishInterfacePropertiesQueryRequest,
    BatfishNodePropertiesQueryRequest,
    BatfishOspfFactsQueryRequest,
    BatfishQueryResponse,
    BatfishReachabilityQueryRequest,
    BatfishRoutesQueryRequest,
    BatfishTestFiltersQueryRequest,
    BatfishTracerouteQueryRequest,
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
    assert_snapshot_exists,
    query_bgp_edges,
    query_bgp_peer_configuration,
    query_bgp_process_configuration,
    query_bgp_session_status,
    query_compare_filters,
    query_differential_reachability,
    query_file_parse_status,
    query_generic,
    query_init_issues,
    query_interface_properties,
    query_node_properties,
    query_ospf_area_configuration,
    query_ospf_edges,
    query_ospf_interface_configuration,
    query_ospf_process_configuration,
    query_parse_warnings,
    query_reachability,
    query_routes,
    query_test_filters,
    query_traceroute,
    require_field,
    resolve_latest_snapshot_name,
)
from services.batfish.source_config_service import BatfishSourceConfigService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParseDiagnostics:
    """The three parse-time answers of one snapshot (``fileParseStatus``, ``parseWarning``,
    ``initIssues``). A question that failed has no rows and an entry in ``unavailable``."""

    snapshot: str
    file_status: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    unavailable: dict[str, str] = field(default_factory=dict)
    truncated: bool = False
    # The sections (files / warnings / issues) whose answer had more rows than the preview cap, so
    # their counts and groups cover only a prefix.
    truncated_sections: tuple[str, ...] = ()


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

    async def _resolve_pair(
        self, source_id: str, network: str, snapshot: str | None, reference_snapshot: str
    ) -> tuple[BatfishConnection, str, str]:
        """Both snapshots of a differential question: ``snapshot`` (default newest) and an
        explicit ``reference_snapshot`` that must exist and differ from it."""
        connection, resolved = await self._resolve(source_id, network, snapshot)
        reference = reference_snapshot.strip()
        if not reference:
            raise ValueError("reference_snapshot is required")
        if reference == resolved:
            raise ValueError(
                f"The reference snapshot must differ from the snapshot compared ({resolved!r})."
            )
        await assert_snapshot_exists(self._batfish, connection, network.strip(), reference)
        return connection, resolved, reference

    async def run_compare_filters(
        self, source_id: str, request: BatfishCompareFiltersQueryRequest
    ) -> BatfishQueryResponse:
        connection, snapshot, reference = await self._resolve_pair(
            source_id, request.network, request.snapshot, request.reference_snapshot
        )
        rows = await query_compare_filters(
            self._batfish,
            connection,
            batfish_network=request.network.strip(),
            snapshot=snapshot,
            reference_snapshot=reference,
            nodes=request.nodes,
            filters=request.filters,
        )
        return BatfishQueryResponse(
            success=True,
            question="compareFilters",
            network=request.network,
            snapshot=snapshot,
            reference_snapshot=reference,
            rows=rows,
        )

    async def run_differential_reachability(
        self, source_id: str, request: BatfishDifferentialReachabilityQueryRequest
    ) -> BatfishQueryResponse:
        start_node = require_field(request.start_node, "start_node")
        connection, snapshot, reference = await self._resolve_pair(
            source_id, request.network, request.snapshot, request.reference_snapshot
        )
        rows = await query_differential_reachability(
            self._batfish,
            connection,
            batfish_network=request.network.strip(),
            snapshot=snapshot,
            reference_snapshot=reference,
            start_node=start_node,
            end_node=request.end_node,
            dst_ips=request.dst_ips,
            src_ips=request.src_ips,
            applications=request.applications,
            ip_protocols=request.ip_protocols,
            max_traces=request.max_traces,
            ignore_filters=request.ignore_filters,
        )
        return BatfishQueryResponse(
            success=True,
            question="differentialReachability",
            network=request.network,
            snapshot=snapshot,
            reference_snapshot=reference,
            rows=rows,
        )

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

    async def run_traceroute(
        self, source_id: str, request: BatfishTracerouteQueryRequest
    ) -> BatfishQueryResponse:
        start_node = require_field(request.start_node, "start_node")
        dst_ips = require_field(request.dst_ips, "dst_ips")
        connection, snapshot = await self._resolve(source_id, request.network, request.snapshot)
        rows = await query_traceroute(
            self._batfish,
            connection,
            batfish_network=request.network,
            snapshot=snapshot,
            start_node=start_node,
            dst_ips=dst_ips,
            src_ips=request.src_ips,
            applications=request.applications,
            ip_protocols=request.ip_protocols,
            max_traces=request.max_traces,
        )
        return BatfishQueryResponse(
            success=True,
            question="traceroute",
            network=request.network,
            snapshot=snapshot,
            rows=rows,
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

    async def run_interface_rows(
        self, source_id: str, request: BatfishInterfacePropertiesQueryRequest
    ) -> BatfishQueryResponse:
        """Like ``run_interface_properties`` but the flat answer table, one row per interface,
        without the per-node grouping (for callers that filter and page rows themselves)."""
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
        return BatfishQueryResponse(
            success=True,
            question=INTERFACE_PROPERTIES_SPEC.question_label,
            network=request.network,
            snapshot=snapshot,
            rows=rows,
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

    async def run_parse_diagnostics(
        self, source_id: str, network: str, snapshot: str | None
    ) -> ParseDiagnostics:
        """Why a snapshot looks the way it does: which files failed to parse, which lines the
        parser did not understand, and what the model build complained about.

        The questions run one after the other (they share one pybatfish session). One that
        fails is reported in ``unavailable`` so the others still answer; if all fail the first
        error is raised, so a dead coordinator is not mistaken for a clean snapshot.
        """
        connection, resolved = await self._resolve(source_id, network, snapshot)
        clean_network = network.strip()
        questions = (
            ("files", query_file_parse_status),
            ("warnings", query_parse_warnings),
            ("issues", query_init_issues),
        )
        rows: dict[str, list[dict[str, Any]]] = {}
        failed: dict[str, Exception] = {}
        for key, query in questions:
            try:
                rows[key] = await query(
                    self._batfish, connection, batfish_network=clean_network, snapshot=resolved
                )
            except Exception as exc:
                logger.warning("Batfish parse diagnostics question %s failed: %s", key, exc)
                failed[key] = exc
        if len(failed) == len(questions):
            raise next(iter(failed.values()))
        cut = tuple(key for key, found in rows.items() if len(found) > MAX_PREVIEW_ROWS)
        return ParseDiagnostics(
            snapshot=resolved,
            file_status=rows.get("files", [])[:MAX_PREVIEW_ROWS],
            warnings=rows.get("warnings", [])[:MAX_PREVIEW_ROWS],
            issues=rows.get("issues", [])[:MAX_PREVIEW_ROWS],
            unavailable={key: type(exc).__name__ for key, exc in failed.items()},
            truncated=bool(cut),
            truncated_sections=cut,
        )

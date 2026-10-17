"""Tests for BatfishPreviewService: the ad-hoc, non-WorkflowRun counterpart of
the batfish-routing-table/batfish-path-check/batfish-acl-check workflow-step
executors, used by the Template Editor's Options modal. BatfishService and
BatfishSourceConfigService are mocked throughout -- these tests never talk to
a real coordinator.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from models.batfish import (
    BatfishBgpFactsQueryRequest,
    BatfishExtractFactsQueryRequest,
    BatfishGenericQueryRequest,
    BatfishInterfacePropertiesQueryRequest,
    BatfishNodePropertiesQueryRequest,
    BatfishOspfFactsQueryRequest,
    BatfishReachabilityQueryRequest,
    BatfishRoutesQueryRequest,
    BatfishTestFiltersQueryRequest,
)
from services.batfish.credentials import BatfishConnection
from services.batfish.preview_service import BatfishPreviewService


def _connection() -> BatfishConnection:
    return BatfishConnection(host="batfish", port=9996)


def _make_service(*, resolved_connection: BatfishConnection | None = None) -> tuple[
    BatfishPreviewService, MagicMock, MagicMock
]:
    source_config_service = MagicMock()
    source_config_service.resolve_connection.return_value = (
        resolved_connection or _connection()
    )
    batfish_service = MagicMock()
    # Every network name used across this file's requests must be "known"
    # to the assert_batfish_network_exists() guard _resolve() now calls
    # first -- otherwise it raises before the test's actual mock (routes/
    # reachability/test_filters) is ever reached.
    batfish_service.list_networks = AsyncMock(return_value=["net", "manus-production"])
    service = BatfishPreviewService(source_config_service, batfish_service)
    return service, source_config_service, batfish_service


class BatfishPreviewServiceRoutesTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_explicit_snapshot_without_listing(self) -> None:
        service, _, batfish = _make_service()
        batfish.routes = AsyncMock(return_value=[{"Node": "r1"}])
        batfish.list_snapshots_with_metadata = AsyncMock()

        result = await service.run_routes(
            "lab",
            BatfishRoutesQueryRequest(network="manus-production", snapshot="run-7"),
        )

        self.assertTrue(result.success)
        self.assertEqual(result.question, "routes")
        self.assertEqual(result.snapshot, "run-7")
        self.assertEqual(result.rows, [{"Node": "r1"}])
        batfish.list_snapshots_with_metadata.assert_not_called()
        batfish.routes.assert_awaited_once()
        _, kwargs = batfish.routes.await_args
        self.assertEqual(kwargs["batfish_network"], "manus-production")
        self.assertEqual(kwargs["snapshot"], "run-7")

    async def test_resolves_latest_snapshot_when_blank(self) -> None:
        service, _, batfish = _make_service()
        batfish.routes = AsyncMock(return_value=[])
        batfish.list_snapshots_with_metadata = AsyncMock(
            return_value=[
                {"name": "run-9", "metadata": {"creationTimestamp": "2026-09-12T10:00:00Z"}},
                {"name": "run-10", "metadata": {"creationTimestamp": "2026-09-12T12:00:00Z"}},
            ]
        )

        result = await service.run_routes(
            "lab", BatfishRoutesQueryRequest(network="manus-production")
        )

        self.assertEqual(result.snapshot, "run-10")

    async def test_nonexistent_network_raises_value_error_without_listing_snapshots(
        self,
    ) -> None:
        """The critical regression test: an unconfirmed network must never
        reach list_snapshots_with_metadata (-> _get_session -> set_network()),
        which would silently CREATE it on the coordinator."""
        service, _, batfish = _make_service()
        batfish.list_networks = AsyncMock(return_value=["some-other-network"])
        batfish.list_snapshots_with_metadata = AsyncMock()
        batfish.routes = AsyncMock()

        with self.assertRaises(ValueError):
            await service.run_routes(
                "lab", BatfishRoutesQueryRequest(network="manus-production")
            )

        batfish.list_snapshots_with_metadata.assert_not_called()
        batfish.routes.assert_not_called()

    async def test_blank_string_params_are_omitted(self) -> None:
        service, _, batfish = _make_service()
        batfish.routes = AsyncMock(return_value=[])

        await service.run_routes(
            "lab",
            BatfishRoutesQueryRequest(network="net", snapshot="snap", nodes="  ", rib=""),
        )

        _, kwargs = batfish.routes.await_args
        self.assertIsNone(kwargs["nodes"])
        self.assertIsNone(kwargs["rib"])


class BatfishPreviewServiceReachabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_start_node(self) -> None:
        # require_field (services.batfish.query_helpers) raises ValueError --
        # the shared check also used by the batfish-path-check executor.
        service, _, _batfish = _make_service()
        with self.assertRaises(ValueError):
            await service.run_reachability(
                "lab",
                BatfishReachabilityQueryRequest(network="net", snapshot="snap", start_node=" "),
            )

    async def test_builds_path_constraints_and_headers(self) -> None:
        service, _, batfish = _make_service()
        batfish.reachability = AsyncMock(return_value=[{"Flow": "f1"}])

        result = await service.run_reachability(
            "lab",
            BatfishReachabilityQueryRequest(
                network="net",
                snapshot="snap",
                start_node="R1",
                end_node="R2",
                dst_ips="192.168.1.1",
                applications=["SSH"],
            ),
        )

        self.assertTrue(result.reachable)
        self.assertEqual(len(result.rows), 1)
        _, kwargs = batfish.reachability.await_args
        self.assertEqual(
            kwargs["pathConstraints"], {"startLocation": "R1", "endLocation": "R2"}
        )
        self.assertEqual(kwargs["headers"], {"dstIps": "192.168.1.1", "applications": ["SSH"]})

    async def test_not_reachable_when_no_rows(self) -> None:
        service, _, batfish = _make_service()
        batfish.reachability = AsyncMock(return_value=[])

        result = await service.run_reachability(
            "lab",
            BatfishReachabilityQueryRequest(network="net", snapshot="snap", start_node="R1"),
        )

        self.assertFalse(result.reachable)
        self.assertEqual(result.rows, [])

    async def test_no_headers_passes_none(self) -> None:
        service, _, batfish = _make_service()
        batfish.reachability = AsyncMock(return_value=[])

        await service.run_reachability(
            "lab",
            BatfishReachabilityQueryRequest(network="net", snapshot="snap", start_node="R1"),
        )

        _, kwargs = batfish.reachability.await_args
        self.assertIsNone(kwargs["headers"])


class BatfishPreviewServiceTestFiltersTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_node_filter_and_dst_ips(self) -> None:
        # Pydantic's min_length=1 already rejects "" at the request-model
        # layer; a whitespace-only string is what exercises require_field()
        # (services.batfish.query_helpers), which raises ValueError -- the
        # same shared check the batfish-acl-check executor uses.
        service, _, _batfish = _make_service()
        with self.assertRaises(ValueError):
            await service.run_test_filters(
                "lab",
                BatfishTestFiltersQueryRequest(
                    network="net", node=" ", filter_name="ACL", dst_ips="1.1.1.1"
                ),
            )
        with self.assertRaises(ValueError):
            await service.run_test_filters(
                "lab",
                BatfishTestFiltersQueryRequest(
                    network="net", node="R1", filter_name=" ", dst_ips="1.1.1.1"
                ),
            )
        with self.assertRaises(ValueError):
            await service.run_test_filters(
                "lab",
                BatfishTestFiltersQueryRequest(
                    network="net", node="R1", filter_name="ACL", dst_ips=" "
                ),
            )

    async def test_returns_action_from_first_row(self) -> None:
        service, _, batfish = _make_service()
        batfish.test_filters = AsyncMock(
            return_value=[{"Action": "PERMIT", "Line_Content": "permit tcp any any eq 22"}]
        )

        result = await service.run_test_filters(
            "lab",
            BatfishTestFiltersQueryRequest(
                network="net", snapshot="snap", node="R1", filter_name="TEST-ACL", dst_ips="1.1.1.1"
            ),
        )

        self.assertEqual(result.action, "PERMIT")
        _, kwargs = batfish.test_filters.await_args
        self.assertEqual(kwargs["headers"], {"dstIps": "1.1.1.1"})

    async def test_raises_when_no_result(self) -> None:
        # An empty result set is an execution problem (node/filter_name
        # didn't match anything), not a verdict -- query_test_filters raises
        # RuntimeError, matching the batfish-acl-check executor's own
        # reasoning (see doc/BATFISH_INTEGRATION.md "Batfish ACL Check").
        service, _, batfish = _make_service()
        batfish.test_filters = AsyncMock(return_value=[])

        with self.assertRaises(RuntimeError):
            await service.run_test_filters(
                "lab",
                BatfishTestFiltersQueryRequest(
                    network="net",
                    snapshot="snap",
                    node="R1",
                    filter_name="TEST-ACL",
                    dst_ips="1.1.1.1",
                ),
            )


class BatfishPreviewServiceGenericTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_question(self) -> None:
        service, _, _batfish = _make_service()
        with self.assertRaises(ValueError):
            await service.run_generic(
                "lab", BatfishGenericQueryRequest(network="net", question=" ")
            )

    async def test_rejects_non_allowlisted_question(self) -> None:
        service, _, batfish = _make_service()
        batfish.generic_question = AsyncMock()

        with self.assertRaises(ValueError):
            await service.run_generic(
                "lab",
                BatfishGenericQueryRequest(network="net", snapshot="snap", question="dropTables"),
            )
        batfish.generic_question.assert_not_awaited()

    async def test_allowlisted_question_returns_rows(self) -> None:
        service, _, batfish = _make_service()
        batfish.generic_question = AsyncMock(return_value=[{"Node": "r1"}])

        result = await service.run_generic(
            "lab",
            BatfishGenericQueryRequest(
                network="net", snapshot="snap", question="edges", params={}
            ),
        )

        self.assertTrue(result.success)
        self.assertEqual(result.question, "edges")
        self.assertEqual(result.rows, [{"Node": "r1"}])


class BatfishPreviewServiceExtractFactsTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_facts_by_node_from_raw_nodes_dict(self) -> None:
        service, _, batfish = _make_service()
        batfish.extract_facts = AsyncMock(
            return_value={"nodes": {"lab": {"Hostname": "lab"}}, "version": "batfish_v0"}
        )

        result = await service.run_extract_facts(
            "lab", BatfishExtractFactsQueryRequest(network="net", snapshot="snap")
        )

        self.assertEqual(result.question, "extractFacts")
        self.assertEqual(result.rows, [])
        self.assertEqual(result.facts_by_node, {"lab": {"Hostname": "lab"}})
        _, kwargs = batfish.extract_facts.await_args
        self.assertEqual(kwargs["nodes"], "/.*/")

    async def test_blank_nodes_filter_defaults_to_every_node(self) -> None:
        service, _, batfish = _make_service()
        batfish.extract_facts = AsyncMock(return_value={"nodes": {}})

        await service.run_extract_facts(
            "lab",
            BatfishExtractFactsQueryRequest(network="net", snapshot="snap", nodes_filter="  "),
        )

        _, kwargs = batfish.extract_facts.await_args
        self.assertEqual(kwargs["nodes"], "/.*/")

    async def test_explicit_nodes_filter_passed_through(self) -> None:
        service, _, batfish = _make_service()
        batfish.extract_facts = AsyncMock(return_value={"nodes": {}})

        await service.run_extract_facts(
            "lab",
            BatfishExtractFactsQueryRequest(
                network="net", snapshot="snap", nodes_filter="lab,lab-2"
            ),
        )

        _, kwargs = batfish.extract_facts.await_args
        self.assertEqual(kwargs["nodes"], "lab,lab-2")

    async def test_malformed_facts_dict_returns_empty_facts_by_node(self) -> None:
        service, _, batfish = _make_service()
        batfish.extract_facts = AsyncMock(return_value={})

        result = await service.run_extract_facts(
            "lab", BatfishExtractFactsQueryRequest(network="net", snapshot="snap")
        )

        self.assertEqual(result.facts_by_node, {})


class BatfishPreviewServiceOspfFactsTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_at_least_one_question_enabled(self) -> None:
        service, _, _batfish = _make_service()
        with self.assertRaises(ValueError):
            await service.run_ospf_facts(
                "lab",
                BatfishOspfFactsQueryRequest(
                    network="net",
                    include_process=False,
                    include_areas=False,
                    include_interfaces=False,
                    include_edges=False,
                ),
            )

    async def test_merges_enabled_questions_per_node(self) -> None:
        service, _, batfish = _make_service()
        batfish.ospf_process_configuration = AsyncMock(
            return_value=[{"Node": "r1", "VRF": "default"}]
        )
        batfish.ospf_area_configuration = AsyncMock(return_value=[{"Node": "r1", "Area": "0"}])

        result = await service.run_ospf_facts(
            "lab",
            BatfishOspfFactsQueryRequest(
                network="net",
                snapshot="snap",
                include_process=True,
                include_areas=True,
                include_interfaces=False,
                include_edges=False,
            ),
        )

        self.assertEqual(result.question, "ospfFacts")
        self.assertEqual(result.rows, [])
        self.assertEqual(
            result.facts_by_node,
            {"r1": {"Process": [{"VRF": "default"}], "Areas": [{"Area": "0"}]}},
        )
        batfish.ospf_interface_configuration.assert_not_called()
        batfish.ospf_edges.assert_not_called()

    async def test_zero_matching_nodes_returns_empty_facts_by_node(self) -> None:
        service, _, batfish = _make_service()
        batfish.ospf_process_configuration = AsyncMock(return_value=[])
        batfish.ospf_area_configuration = AsyncMock(return_value=[])
        batfish.ospf_interface_configuration = AsyncMock(return_value=[])
        batfish.ospf_edges = AsyncMock(return_value=[])

        result = await service.run_ospf_facts(
            "lab", BatfishOspfFactsQueryRequest(network="net", snapshot="snap")
        )

        self.assertEqual(result.facts_by_node, {})


class BatfishPreviewServiceBgpFactsTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_at_least_one_question_enabled(self) -> None:
        service, _, _batfish = _make_service()
        with self.assertRaises(ValueError):
            await service.run_bgp_facts(
                "lab",
                BatfishBgpFactsQueryRequest(
                    network="net",
                    include_process=False,
                    include_peers=False,
                    include_sessions=False,
                    include_edges=False,
                ),
            )

    async def test_merges_enabled_questions_per_node(self) -> None:
        service, _, batfish = _make_service()
        batfish.bgp_peer_configuration = AsyncMock(
            return_value=[{"Node": "r1", "Remote_AS": "200"}]
        )

        result = await service.run_bgp_facts(
            "lab",
            BatfishBgpFactsQueryRequest(
                network="net",
                snapshot="snap",
                include_process=False,
                include_peers=True,
                include_sessions=False,
                include_edges=False,
            ),
        )

        self.assertEqual(result.question, "bgpFacts")
        self.assertEqual(result.facts_by_node, {"r1": {"Peers": [{"Remote_AS": "200"}]}})
        batfish.bgp_process_configuration.assert_not_called()


class BatfishPreviewServiceNodePropertiesTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_facts_by_node_grouped(self) -> None:
        service, _, batfish = _make_service()
        batfish.node_properties = AsyncMock(
            return_value=[{"Node": "r1", "NTP_Servers": ["10.0.0.1"]}]
        )

        result = await service.run_node_properties(
            "lab", BatfishNodePropertiesQueryRequest(network="net", snapshot="snap")
        )

        self.assertEqual(result.question, "nodeProperties")
        self.assertEqual(result.facts_by_node, {"r1": {"NTP_Servers": ["10.0.0.1"]}})

    async def test_passes_nodes_and_properties_through(self) -> None:
        service, _, batfish = _make_service()
        batfish.node_properties = AsyncMock(return_value=[])

        await service.run_node_properties(
            "lab",
            BatfishNodePropertiesQueryRequest(
                network="net", snapshot="snap", nodes="r1", properties="NTP_Servers"
            ),
        )

        _, kwargs = batfish.node_properties.await_args
        self.assertEqual(kwargs["nodes"], "r1")
        self.assertEqual(kwargs["properties"], "NTP_Servers")


class BatfishPreviewServiceInterfacePropertiesTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_facts_by_node_nested_under_interfaces(self) -> None:
        service, _, batfish = _make_service()
        batfish.interface_properties = AsyncMock(
            return_value=[
                {
                    "Interface": {"hostname": "r1", "interface": "GigabitEthernet0/1"},
                    "Access_VLAN": 10,
                }
            ]
        )

        result = await service.run_interface_properties(
            "lab", BatfishInterfacePropertiesQueryRequest(network="net", snapshot="snap")
        )

        self.assertEqual(result.question, "interfaceProperties")
        self.assertEqual(
            result.facts_by_node,
            {"r1": {"Interfaces": {"GigabitEthernet0/1": {"Access_VLAN": 10}}}},
        )

    async def test_passes_interfaces_filter_through(self) -> None:
        service, _, batfish = _make_service()
        batfish.interface_properties = AsyncMock(return_value=[])

        await service.run_interface_properties(
            "lab",
            BatfishInterfacePropertiesQueryRequest(
                network="net", snapshot="snap", interfaces="GigabitEthernet0/1"
            ),
        )

        _, kwargs = batfish.interface_properties.await_args
        self.assertEqual(kwargs["interfaces"], "GigabitEthernet0/1")


if __name__ == "__main__":
    unittest.main()

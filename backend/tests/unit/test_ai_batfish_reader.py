"""DbBatfishReader: permission, rate limit, source lookup, error mapping, row cap.

Database, RBAC, the rate limiter and Batfish are mocked; nothing talks to a real service.
"""

from __future__ import annotations

import unittest
import unittest.mock
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

from models.batfish import BatfishQueryResponse
from services.ai_assistant.batfish_reader import NODE_CACHE, DbBatfishReader
from services.ai_assistant.tools.batfish_tools import (
    BatfishAccessError,
    BatfishInputError,
    BatfishUnavailableError,
)
from services.auth.login_rate_limiter import RateLimitExceededError
from services.batfish.client import PREVIEW_ROW_LIMIT
from services.batfish.common.exceptions import (
    BatfishAnswerFailedError,
    BatfishAPIError,
    FilterNotFoundError,
)
from services.batfish.credentials import BatfishConnection
from services.batfish.preview_service import ParseDiagnostics
from services.batfish.source_config_service import BatfishSourceNotFoundError

MOD = "services.ai_assistant.batfish_reader"


def _response(question: str = "routes", rows=None, snapshot: str = "run-2", truncated=False):
    return BatfishQueryResponse(
        success=True,
        question=question,
        network="net1",
        snapshot=snapshot,
        rows=rows or [],
        truncated=truncated,
    )


class ReaderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.rbac = MagicMock()
        self.rbac.return_value.has_permission.return_value = True
        stack.enter_context(patch(f"{MOD}.RBACService", self.rbac))
        stack.enter_context(patch(f"{MOD}.SessionLocal", MagicMock()))
        self.sources = MagicMock()
        self.sources.return_value.list_sources.return_value = [
            {"source_id": "lab"},
            {"source_id": "b"},
        ]
        self.sources.return_value.resolve_connection.return_value = BatfishConnection(
            host="bf", port=1
        )
        stack.enter_context(patch(f"{MOD}.BatfishSourceConfigService", self.sources))
        self.limiter = MagicMock()
        self.factory = stack.enter_context(patch(f"{MOD}.service_factory"))
        self.factory.build_user_rate_limiter.return_value = self.limiter
        self.batfish = MagicMock()
        self.batfish.list_networks = AsyncMock(return_value=["net1"])
        self.batfish.list_snapshots_with_metadata = AsyncMock(
            return_value=[
                {"name": "run-1", "metadata": {"creationTimestamp": "2026-10-01T00:00:00Z"}},
                {"name": "run-2", "metadata": {"creationTimestamp": "2026-11-01T00:00:00Z"}},
            ]
        )
        self.batfish.node_properties = AsyncMock(
            return_value=[{"Node": "lab"}, {"Node": "r1"}, {"Node": "r2"}, {"Node": "sw.corp.zz"}]
        )
        NODE_CACHE.clear()
        self.addCleanup(NODE_CACHE.clear)
        self.factory.get_batfish_app_service.return_value = self.batfish
        self.preview = MagicMock()
        for name in ("run_routes", "run_traceroute", "run_generic", "run_interface_rows"):
            setattr(self.preview, name, AsyncMock(return_value=_response()))
        for name, question in (
            ("run_compare_filters", "compareFilters"),
            ("run_differential_reachability", "differentialReachability"),
        ):
            diff = _response(question)
            diff.reference_snapshot = "run-1"
            setattr(self.preview, name, AsyncMock(return_value=diff))
        self.preview.run_parse_diagnostics = AsyncMock(
            return_value=ParseDiagnostics(
                snapshot="run-2",
                file_status=[{"File_Name": "r1.cfg", "Status": "FAILED"}],
                warnings=[],
                issues=[],
                unavailable={"issues": "BatfishAPIError"},
                truncated=True,
                truncated_sections=("files",),
            )
        )
        self.preview.run_reachability = AsyncMock(return_value=_response("reachability"))
        self.preview.run_test_filters = AsyncMock(return_value=_response("testFilters"))
        self.preview.run_extract_facts = AsyncMock(
            return_value=BatfishQueryResponse(
                success=True,
                question="extractFacts",
                network="net1",
                snapshot="run-2",
                rows=[],
                facts_by_node={"r1": {"Hostname": "r1"}, "r2": {"Hostname": "r2"}},
            )
        )
        stack.enter_context(
            patch(f"{MOD}.BatfishPreviewService", MagicMock(return_value=self.preview))
        )
        self.reader = DbBatfishReader(user_id=7)

    # -- permission / limits -----------------------------------------------------------------

    async def test_needs_the_batfish_query_permission(self) -> None:
        self.rbac.return_value.has_permission.return_value = False

        for call in (
            self.reader.list_sources(),
            self.reader.list_networks("lab"),
            self.reader.list_snapshots("lab", "net1"),
            self.reader.query("routes", "lab", "net1", None, {}),
        ):
            with self.subTest(call.__qualname__):
                with self.assertRaises(BatfishAccessError):
                    await call
        self.rbac.return_value.has_permission.assert_called_with(7, "sources.batfish", "query")
        self.preview.run_routes.assert_not_called()

    async def test_uses_the_same_rate_limit_bucket_as_the_query_router(self) -> None:
        await self.reader.list_networks("lab")

        self.factory.build_user_rate_limiter.assert_called_with("batfish-query", 30, 60)
        self.limiter.check.assert_called_with("batfish-query:7")

    async def test_rate_limit_is_a_clear_input_error(self) -> None:
        self.limiter.check.side_effect = RateLimitExceededError("k")

        with self.assertRaises(BatfishInputError) as ctx:
            await self.reader.query("routes", "lab", "net1", None, {})
        self.assertIn("Too many", str(ctx.exception))
        self.preview.run_routes.assert_not_called()

    # -- discovery ---------------------------------------------------------------------------

    async def test_list_sources_returns_ids(self) -> None:
        self.assertEqual(await self.reader.list_sources(), ["lab", "b"])

    async def test_list_networks(self) -> None:
        self.assertEqual(await self.reader.list_networks("lab"), ["net1"])

    async def test_list_snapshots_returns_name_and_created(self) -> None:
        snapshots = await self.reader.list_snapshots("lab", "net1")

        self.assertEqual(
            snapshots,
            [
                {"name": "run-1", "created": "2026-10-01T00:00:00Z"},
                {"name": "run-2", "created": "2026-11-01T00:00:00Z"},
            ],
        )

    async def test_list_snapshots_of_a_missing_network_never_creates_it(self) -> None:
        self.batfish.list_networks = AsyncMock(return_value=["other"])

        with self.assertRaises(BatfishInputError):
            await self.reader.list_snapshots("lab", "net1")
        self.batfish.list_snapshots_with_metadata.assert_not_called()

    async def test_unknown_source_is_an_input_error(self) -> None:
        self.sources.return_value.resolve_connection.side_effect = BatfishSourceNotFoundError("zzz")

        with self.assertRaises(BatfishInputError) as ctx:
            await self.reader.list_networks("zzz")
        self.assertIn("zzz", str(ctx.exception))

    # -- queries -----------------------------------------------------------------------------

    async def test_routes_query_builds_the_request_and_reports_the_snapshot_age(self) -> None:
        self.preview.run_routes.return_value = _response(rows=[{"Node": "r1"}])

        answer = await self.reader.query(
            "routes",
            "lab",
            "net1",
            None,
            {
                "nodes": "r1",
                "network_prefix": "10.1.2.3/32",
                "prefix_match_type": "LONGEST_PREFIX_MATCH",
                "protocols": None,
                "vrfs": None,
            },
        )

        self.assertEqual(answer.rows, [{"Node": "r1"}])
        self.assertEqual(answer.snapshot, "run-2")
        self.assertEqual(answer.snapshot_created, "2026-11-01T00:00:00Z")
        source, request = self.preview.run_routes.await_args.args
        self.assertEqual(source, "lab")
        self.assertEqual(
            (request.network, request.nodes, request.network_prefix), ("net1", "r1", "10.1.2.3/32")
        )

    async def test_each_kind_goes_to_its_preview_method(self) -> None:
        await self.reader.query(
            "traceroute",
            "lab",
            "net1",
            "run-2",
            {
                "start_node": "r1",
                "dst_ips": "10.0.0.1",
                "src_ips": None,
                "applications": None,
                "ip_protocols": None,
                "max_traces": 5,
            },
        )
        await self.reader.query("bgp_sessions", "lab", "net1", None, {"nodes": "r1"})
        await self.reader.query(
            "interfaces", "lab", "net1", None, {"nodes": "r1", "interfaces": "Gi0/1"}
        )

        self.assertEqual(self.preview.run_traceroute.await_args.args[1].start_node, "r1")
        generic = self.preview.run_generic.await_args.args[1]
        self.assertEqual((generic.question, generic.params), ("bgpSessionStatus", {"nodes": "r1"}))
        self.assertEqual(self.preview.run_interface_rows.await_args.args[1].interfaces, "Gi0/1")

    async def test_facts_become_one_row_per_node_and_the_filter_is_forwarded(self) -> None:
        answer = await self.reader.query("facts", "lab", "net1", None, {"nodes": "r1,r2"})

        request = self.preview.run_extract_facts.await_args.args[1]
        self.assertEqual(request.nodes_filter, "r1,r2")
        self.assertEqual(
            answer.rows,
            [
                {"Node": "r1", "Facts": {"Hostname": "r1"}},
                {"Node": "r2", "Facts": {"Hostname": "r2"}},
            ],
        )

    async def test_facts_without_a_node_list_ask_for_every_node(self) -> None:
        await self.reader.query("facts", "lab", "net1", None, {"nodes": None})

        self.assertEqual(self.preview.run_extract_facts.await_args.args[1].nodes_filter, "/.*/")

    async def test_acl_and_reachability_are_forwarded(self) -> None:
        await self.reader.query(
            "acl",
            "lab",
            "net1",
            None,
            {
                "node": "r1",
                "filter_name": "A",
                "dst_ips": "10.0.0.1",
                "src_ips": None,
                "applications": ["tcp/22"],
                "ip_protocols": None,
            },
        )
        await self.reader.query(
            "reachability",
            "lab",
            "net1",
            None,
            {"start_node": "r1", "end_node": "r2", "dst_ips": "10.0.0.1", "ignore_filters": True},
        )

        acl = self.preview.run_test_filters.await_args.args[1]
        self.assertEqual((acl.node, acl.filter_name, acl.applications), ("r1", "A", ["tcp/22"]))
        reach = self.preview.run_reachability.await_args.args[1]
        self.assertEqual(
            (reach.start_node, reach.end_node, reach.ignore_filters), ("r1", "r2", True)
        )

    async def test_differential_kinds_forward_the_reference_and_report_both_snapshots(self) -> None:
        answer = await self.reader.query(
            "compare_filters",
            "lab",
            "net1",
            "run-2",
            {"reference_snapshot": "run-1", "nodes": "r1", "filters": "A"},
        )
        await self.reader.query(
            "differential_reachability",
            "lab",
            "net1",
            "run-2",
            {"reference_snapshot": "run-1", "start_node": "r1", "dst_ips": "10.0.0.1"},
        )

        request = self.preview.run_compare_filters.await_args.args[1]
        self.assertEqual(
            (request.reference_snapshot, request.nodes, request.filters), ("run-1", "r1", "A")
        )
        self.assertEqual(
            self.preview.run_differential_reachability.await_args.args[1].start_node, "r1"
        )
        self.assertEqual((answer.snapshot, answer.reference_snapshot), ("run-2", "run-1"))
        self.assertEqual(answer.reference_created, "2026-10-01T00:00:00Z")

    async def test_an_acl_that_matches_nothing_is_an_input_error_for_the_model(self) -> None:
        self.preview.run_test_filters.side_effect = FilterNotFoundError("No result returned")

        with self.assertRaises(BatfishInputError) as ctx:
            await self.reader.query(
                "acl",
                "lab",
                "net1",
                None,
                {"node": "r1", "filter_name": "NOPE", "dst_ips": "1.1.1.1"},
            )
        self.assertIn("filter", str(ctx.exception).lower())

    async def test_any_other_runtime_error_from_the_acl_query_means_unavailable(self) -> None:
        self.preview.run_test_filters.side_effect = RuntimeError("event loop is closed")

        with self.assertRaises(BatfishUnavailableError):
            await self.reader.query(
                "acl",
                "lab",
                "net1",
                None,
                {"node": "r1", "filter_name": "A", "dst_ips": "1.1.1.1"},
            )

    async def test_the_preview_row_cap_is_set_during_the_query_and_reset_after(self) -> None:
        seen: list[int | None] = []

        async def run_routes(*_a, **_k):
            seen.append(PREVIEW_ROW_LIMIT.get())
            return _response()

        self.preview.run_routes = run_routes

        await self.reader.query("routes", "lab", "net1", None, {})

        self.assertEqual(seen, [5000])
        self.assertIsNone(PREVIEW_ROW_LIMIT.get())

    async def test_cut_tables_are_flagged(self) -> None:
        self.preview.run_routes.return_value = _response(rows=[{"i": 1}], truncated=True)

        answer = await self.reader.query("routes", "lab", "net1", None, {})

        self.assertTrue(answer.truncated)

    async def test_snapshot_age_lookup_failure_does_not_fail_the_query(self) -> None:
        self.batfish.list_snapshots_with_metadata = AsyncMock(side_effect=BatfishAPIError("x"))

        answer = await self.reader.query("routes", "lab", "net1", None, {})

        self.assertIsNone(answer.snapshot_created)

    # -- error mapping -----------------------------------------------------------------------

    async def test_errors_are_mapped_without_internal_text(self) -> None:
        cases = (
            (ValueError("Batfish network 'x' does not exist on this source"), BatfishInputError),
            (BatfishAnswerFailedError("routes", {"secret": "internal"}), BatfishInputError),
            (BatfishAPIError("connection refused to 10.9.9.9:9996"), BatfishUnavailableError),
            (RuntimeError("boom"), BatfishUnavailableError),
        )
        for error, expected in cases:
            with self.subTest(type(error).__name__):
                self.preview.run_routes.side_effect = error
                with self.assertRaises(expected) as ctx:
                    await self.reader.query("routes", "lab", "net1", None, {})
                self.assertNotIn("10.9.9.9", str(ctx.exception))
                self.assertNotIn("internal", str(ctx.exception))

    async def test_unknown_kind_is_rejected(self) -> None:
        with self.assertRaises(BatfishInputError):
            await self.reader.query("shell", "lab", "net1", None, {})  # type: ignore[arg-type]

    # -- review round 2 ----------------------------------------------------------------------

    async def test_the_source_lookup_is_not_charged_to_the_coordinator_budget(self) -> None:
        await self.reader.list_sources()

        self.limiter.check.assert_not_called()

    async def test_one_tool_call_spends_exactly_one_slot(self) -> None:
        # What the tools do for a normal call: find the source, then ask the coordinator.
        await self.reader.list_sources()
        await self.reader.query("routes", "lab", "net1", None, {})

        self.assertEqual(self.limiter.check.call_count, 1)

    async def test_discovery_calls_to_the_coordinator_are_charged_once_each(self) -> None:
        await self.reader.list_networks("lab")
        await self.reader.list_snapshots("lab", "net1")

        self.assertEqual(self.limiter.check.call_count, 2)

    async def test_padded_names_are_stripped_for_the_guard_and_the_call(self) -> None:
        await self.reader.query("routes", "lab", "  net1 ", " run-2 ", {})

        request = self.preview.run_routes.await_args.args[1]
        self.assertEqual((request.network, request.snapshot), ("net1", "run-2"))
        await self.reader.list_snapshots("lab", " net1 ")
        self.batfish.list_snapshots_with_metadata.assert_awaited_with(
            unittest.mock.ANY, batfish_network="net1"
        )

    async def test_a_blank_snapshot_means_the_newest(self) -> None:
        await self.reader.query("routes", "lab", "net1", "   ", {})

        self.assertIsNone(self.preview.run_routes.await_args.args[1].snapshot)


    # -- snapshot diagnostics ----------------------------------------------------------------
    async def test_returns_the_rows_with_snapshot_age(self) -> None:
        result = await self.reader.snapshot_diagnostics("lab", " net1 ", " run-2 ")

        self.preview.run_parse_diagnostics.assert_awaited_once_with("lab", "net1", "run-2")
        self.assertEqual(result.snapshot, "run-2")
        self.assertEqual(result.snapshot_created, "2026-11-01T00:00:00Z")
        self.assertEqual(result.file_status, [{"File_Name": "r1.cfg", "Status": "FAILED"}])
        self.assertEqual(result.unavailable, {"issues": "BatfishAPIError"})
        self.assertTrue(result.truncated)
        self.assertEqual(result.truncated_sections, ("files",))

    async def test_blank_snapshot_means_the_newest(self) -> None:
        await self.reader.snapshot_diagnostics("lab", "net1", "  ")

        self.assertIsNone(self.preview.run_parse_diagnostics.await_args.args[2])

    async def test_one_permission_check_and_one_rate_limit_charge(self) -> None:
        await self.reader.snapshot_diagnostics("lab", "net1", None)

        self.assertEqual(self.limiter.check.call_count, 1)

    async def test_permission_is_required_and_nothing_is_asked(self) -> None:
        self.rbac.return_value.has_permission.return_value = False

        with self.assertRaises(BatfishAccessError):
            await self.reader.snapshot_diagnostics("lab", "net1", None)
        self.preview.run_parse_diagnostics.assert_not_awaited()

    async def test_row_cap_is_applied_to_the_questions(self) -> None:
        seen: list[int | None] = []

        async def capture(*_: object) -> ParseDiagnostics:
            seen.append(PREVIEW_ROW_LIMIT.get())
            return ParseDiagnostics("run-2", [], [], [])

        self.preview.run_parse_diagnostics = AsyncMock(side_effect=capture)
        await self.reader.snapshot_diagnostics("lab", "net1", None)

        self.assertIsNotNone(seen[0])
        self.assertIsNone(PREVIEW_ROW_LIMIT.get())

    async def test_errors_are_reduced_to_the_tool_types(self) -> None:
        for raised, expected in (
            (ValueError("Unknown network 'x'"), BatfishInputError),
            (BatfishAPIError("host:9996 down"), BatfishUnavailableError),
        ):
            self.preview.run_parse_diagnostics = AsyncMock(side_effect=raised)
            with self.assertRaises(expected) as ctx:
                await self.reader.snapshot_diagnostics("lab", "net1", None)
            self.assertNotIn("9996", str(ctx.exception))

    # -- device names ------------------------------------------------------------------------

    async def test_an_fqdn_is_rewritten_to_the_batfish_node_name(self) -> None:
        answer = await self.reader.query(
            "routes", "lab", "net1", None, {"nodes": "LAB.local.zz,r1", "vrfs": "default"}
        )

        request = self.preview.run_routes.await_args.args[1]
        self.assertEqual(request.nodes, "lab,r1")
        self.assertEqual(request.vrfs, "default")
        self.assertEqual(answer.nodes_resolved, {"LAB.local.zz": "lab"})

    async def test_single_node_parameters_are_rewritten_too(self) -> None:
        await self.reader.query(
            "traceroute", "lab", "net1", None, {"start_node": "R1.x.zz", "dst_ips": "10.0.0.1"}
        )

        self.assertEqual(self.preview.run_traceroute.await_args.args[1].start_node, "r1")

    async def test_a_short_name_finds_a_node_that_carries_a_domain(self) -> None:
        await self.reader.query("bgp_sessions", "lab", "net1", None, {"nodes": "sw"})

        generic = self.preview.run_generic.await_args.args[1]
        self.assertEqual(generic.params, {"nodes": "sw.corp.zz"})

    async def test_no_node_parameter_means_no_node_lookup(self) -> None:
        await self.reader.query("routes", "lab", "net1", None, {"nodes": None})

        self.batfish.node_properties.assert_not_awaited()

    async def test_an_unknown_device_is_an_input_error_with_suggestions(self) -> None:
        with self.assertRaises(BatfishInputError) as ctx:
            await self.reader.query("routes", "lab", "net1", None, {"nodes": "r"})

        message = str(ctx.exception)
        self.assertIn("'r'", message)
        self.assertIn("r1", message)
        self.preview.run_routes.assert_not_awaited()

    async def test_an_ambiguous_device_is_never_guessed(self) -> None:
        self.batfish.node_properties = AsyncMock(
            return_value=[{"Node": "x.a.zz"}, {"Node": "x.b.zz"}]
        )

        with self.assertRaises(BatfishInputError) as ctx:
            await self.reader.query("routes", "lab", "net1", None, {"nodes": "x"})

        self.assertIn("x.a.zz", str(ctx.exception))
        self.assertIn("x.b.zz", str(ctx.exception))
        self.preview.run_routes.assert_not_awaited()

    async def test_the_query_runs_on_the_snapshot_the_names_were_checked_against(self) -> None:
        await self.reader.query("routes", "lab", "net1", None, {"nodes": "r1"})

        self.assertEqual(self.batfish.node_properties.await_args.kwargs["snapshot"], "run-2")
        self.assertEqual(self.preview.run_routes.await_args.args[1].snapshot, "run-2")

    async def test_node_names_are_listed_once_per_snapshot(self) -> None:
        await self.reader.query("routes", "lab", "net1", "run-2", {"nodes": "r1"})
        await self.reader.query("bgp_sessions", "lab", "net1", "run-2", {"nodes": "r2"})

        self.assertEqual(self.batfish.node_properties.await_count, 1)

    async def test_the_node_listing_only_asks_for_the_node_column(self) -> None:
        await self.reader.query("routes", "lab", "net1", None, {"nodes": "r1"})

        kwargs = self.batfish.node_properties.await_args.kwargs
        self.assertEqual(kwargs["properties"], "Hostname")
        self.assertIsNone(kwargs["nodes"])

    async def test_when_the_node_list_cannot_be_read_the_query_goes_ahead(self) -> None:
        self.batfish.node_properties = AsyncMock(side_effect=BatfishAPIError("down"))

        await self.reader.query("routes", "lab", "net1", None, {"nodes": "LAB.local.zz"})

        # Not rejected and not rewritten to another device: only spelled the way Batfish does.
        self.assertEqual(self.preview.run_routes.await_args.args[1].nodes, "lab.local.zz")

    async def test_an_empty_node_list_does_not_reject_names(self) -> None:
        self.batfish.node_properties = AsyncMock(return_value=[])

        await self.reader.query("routes", "lab", "net1", None, {"nodes": "r1"})

        self.assertEqual(self.preview.run_routes.await_args.args[1].nodes, "r1")

    # -- node listing ------------------------------------------------------------------------

    async def test_node_names_lists_the_nodes_with_the_snapshot_and_its_age(self) -> None:
        listing = await self.reader.node_names("lab", " net1 ", None)

        self.assertEqual(listing.names, ("lab", "r1", "r2", "sw.corp.zz"))
        self.assertEqual(listing.snapshot, "run-2")
        self.assertEqual(listing.snapshot_created, "2026-11-01T00:00:00Z")

    async def test_node_names_needs_the_permission_and_maps_errors(self) -> None:
        self.rbac.return_value.has_permission.return_value = False
        with self.assertRaises(BatfishAccessError):
            await self.reader.node_names("lab", "net1", None)

        self.rbac.return_value.has_permission.return_value = True
        self.batfish.node_properties = AsyncMock(side_effect=BatfishAPIError("host:9996"))
        with self.assertRaises(BatfishUnavailableError) as ctx:
            await self.reader.node_names("lab", "net1", None)
        self.assertNotIn("9996", str(ctx.exception))

    async def test_node_names_for_an_unknown_network_is_an_input_error(self) -> None:
        with self.assertRaises(BatfishInputError):
            await self.reader.node_names("lab", "typo", None)

    # -- review: spelling and case ------------------------------------------------------------

    async def test_a_case_only_rewrite_is_reported_with_the_users_spelling(self) -> None:
        answer = await self.reader.query("routes", "lab", "net1", None, {"nodes": "LAB,r1"})

        self.assertEqual(self.preview.run_routes.await_args.args[1].nodes, "lab,r1")
        self.assertEqual(answer.nodes_resolved, {"LAB": "lab"})

    async def test_without_a_node_list_names_are_lowercased_as_batfish_spells_them(self) -> None:
        self.batfish.node_properties = AsyncMock(side_effect=BatfishAPIError("down"))
        answer = await self.reader.query("routes", "lab", "net1", None, {"nodes": "LAB,R1"})

        self.assertEqual(self.preview.run_routes.await_args.args[1].nodes, "lab,r1")
        self.assertEqual(answer.nodes_resolved, {})

        self.batfish.node_properties = AsyncMock(return_value=[])
        NODE_CACHE.clear()
        await self.reader.query(
            "traceroute", "lab", "net1", None, {"start_node": "LAB", "dst_ips": "10.0.0.1"}
        )
        self.assertEqual(self.preview.run_traceroute.await_args.args[1].start_node, "lab")

    async def test_the_unknown_name_message_asks_the_user_instead_of_retrying(self) -> None:
        with self.assertRaises(BatfishInputError) as ctx:
            await self.reader.query("routes", "lab", "net1", None, {"nodes": "r"})

        self.assertIn("not necessarily the same device", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

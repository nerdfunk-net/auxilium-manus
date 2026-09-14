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


if __name__ == "__main__":
    unittest.main()

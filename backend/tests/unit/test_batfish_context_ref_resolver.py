"""Tests for workflow_steps.common.batfish_context.resolve_batfish_snapshot_ref."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import WorkflowContext
from services.batfish.credentials import BatfishConnection
from workflow_steps.common.batfish_context import (
    resolve_batfish_snapshot_ref,
    store_batfish_snapshot,
)

_OBJECT_SESSION_TARGET = "workflow_steps.common.batfish_context.object_session"
_CONFIG_SERVICE_TARGET = "workflow_steps.common.batfish_context.BatfishSourceConfigService"


def _context_with_metadata() -> WorkflowContext:
    context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
    return store_batfish_snapshot(
        context,
        connection=BatfishConnection(host="metadata-host", port=9996),
        network="manus-workflow-7",
        snapshot="run-1",
    )


def _run_mock() -> MagicMock:
    run = MagicMock()
    run.id = 42
    return run


class ResolveBatfishSnapshotRefTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_config_wins_over_metadata(self) -> None:
        context = _context_with_metadata()
        run = _run_mock()
        batfish = MagicMock()
        batfish.list_networks = AsyncMock(return_value=["manus-production"])
        batfish.list_snapshots_with_metadata = AsyncMock(
            return_value=[
                {"name": "run-99", "metadata": {"creationTimestamp": "2026-09-12T10:00:00Z"}}
            ]
        )

        with (
            patch(_OBJECT_SESSION_TARGET, return_value=MagicMock()),
            patch(_CONFIG_SERVICE_TARGET) as config_service_cls,
        ):
            config_service_cls.return_value.resolve_connection.return_value = BatfishConnection(
                host="prod-host", port=9996
            )
            ref = await resolve_batfish_snapshot_ref(
                context=context,
                config={"batfish_source_id": "prod-batfish", "network": "manus-production"},
                run=run,
                batfish=batfish,
            )

        self.assertEqual(ref.network, "manus-production")
        self.assertEqual(ref.connection.host, "prod-host")
        self.assertEqual(ref.snapshot, "run-99")

    async def test_falls_back_to_metadata_when_config_incomplete(self) -> None:
        context = _context_with_metadata()
        run = _run_mock()
        batfish = MagicMock()

        ref = await resolve_batfish_snapshot_ref(
            context=context,
            config={"batfish_source_id": "prod-batfish"},  # network missing
            run=run,
            batfish=batfish,
        )

        self.assertEqual(ref.network, "manus-workflow-7")
        self.assertEqual(ref.snapshot, "run-1")
        batfish.list_snapshots_with_metadata.assert_not_called()

    async def test_falls_back_to_metadata_when_config_absent(self) -> None:
        context = _context_with_metadata()
        run = _run_mock()
        batfish = MagicMock()

        ref = await resolve_batfish_snapshot_ref(
            context=context, config={}, run=run, batfish=batfish
        )

        self.assertEqual(ref.connection.host, "metadata-host")
        self.assertEqual(ref.network, "manus-workflow-7")
        self.assertEqual(ref.snapshot, "run-1")

    async def test_no_metadata_and_no_config_raises_value_error(self) -> None:
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        run = _run_mock()
        batfish = MagicMock()

        with self.assertRaises(ValueError):
            await resolve_batfish_snapshot_ref(
                context=context, config={}, run=run, batfish=batfish
            )

    async def test_no_snapshots_in_network_raises_value_error(self) -> None:
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        run = _run_mock()
        batfish = MagicMock()
        batfish.list_networks = AsyncMock(return_value=["manus-production"])
        batfish.list_snapshots_with_metadata = AsyncMock(return_value=[])

        with (
            patch(_OBJECT_SESSION_TARGET, return_value=MagicMock()),
            patch(_CONFIG_SERVICE_TARGET) as config_service_cls,
        ):
            config_service_cls.return_value.resolve_connection.return_value = BatfishConnection(
                host="prod-host", port=9996
            )
            with self.assertRaises(ValueError):
                await resolve_batfish_snapshot_ref(
                    context=context,
                    config={"batfish_source_id": "prod-batfish", "network": "manus-production"},
                    run=run,
                    batfish=batfish,
                )

    async def test_explicit_snapshot_skips_list_call(self) -> None:
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        run = _run_mock()
        batfish = MagicMock()
        batfish.list_networks = AsyncMock(return_value=["manus-production"])
        batfish.list_snapshots_with_metadata = AsyncMock()

        with (
            patch(_OBJECT_SESSION_TARGET, return_value=MagicMock()),
            patch(_CONFIG_SERVICE_TARGET) as config_service_cls,
        ):
            config_service_cls.return_value.resolve_connection.return_value = BatfishConnection(
                host="prod-host", port=9996
            )
            ref = await resolve_batfish_snapshot_ref(
                context=context,
                config={
                    "batfish_source_id": "prod-batfish",
                    "network": "manus-production",
                    "snapshot": "run-7",
                },
                run=run,
                batfish=batfish,
            )

        self.assertEqual(ref.snapshot, "run-7")
        batfish.list_snapshots_with_metadata.assert_not_called()

    async def test_picks_most_recent_by_creation_timestamp(self) -> None:
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        run = _run_mock()
        batfish = MagicMock()
        # Deliberately out of lexical-name order.
        entries = [
            {"name": "run-10", "metadata": {"creationTimestamp": "2026-09-12T10:00:00.000Z"}},
            {"name": "run-9", "metadata": {"creationTimestamp": "2026-09-12T12:00:00.000Z"}},
        ]
        batfish.list_networks = AsyncMock(return_value=["manus-production"])
        batfish.list_snapshots_with_metadata = AsyncMock(return_value=entries)

        with (
            patch(_OBJECT_SESSION_TARGET, return_value=MagicMock()),
            patch(_CONFIG_SERVICE_TARGET) as config_service_cls,
        ):
            config_service_cls.return_value.resolve_connection.return_value = BatfishConnection(
                host="prod-host", port=9996
            )
            ref = await resolve_batfish_snapshot_ref(
                context=context,
                config={"batfish_source_id": "prod-batfish", "network": "manus-production"},
                run=run,
                batfish=batfish,
            )

        self.assertEqual(ref.snapshot, "run-9")

    async def test_nonexistent_network_raises_value_error_without_listing_snapshots(
        self,
    ) -> None:
        """The critical regression test: an unconfirmed network must never
        reach list_snapshots_with_metadata (-> _get_session -> set_network()),
        which would silently CREATE it on the coordinator."""
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        run = _run_mock()
        batfish = MagicMock()
        batfish.list_networks = AsyncMock(return_value=["some-other-network"])
        batfish.list_snapshots_with_metadata = AsyncMock()

        with (
            patch(_OBJECT_SESSION_TARGET, return_value=MagicMock()),
            patch(_CONFIG_SERVICE_TARGET) as config_service_cls,
        ):
            config_service_cls.return_value.resolve_connection.return_value = BatfishConnection(
                host="prod-host", port=9996
            )
            with self.assertRaises(ValueError):
                await resolve_batfish_snapshot_ref(
                    context=context,
                    config={"batfish_source_id": "prod-batfish", "network": "manus-production"},
                    run=run,
                    batfish=batfish,
                )

        batfish.list_snapshots_with_metadata.assert_not_called()

    async def test_no_active_db_session_raises_runtime_error(self) -> None:
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        run = _run_mock()
        batfish = MagicMock()

        with patch(_OBJECT_SESSION_TARGET, return_value=None):
            with self.assertRaises(RuntimeError):
                await resolve_batfish_snapshot_ref(
                    context=context,
                    config={"batfish_source_id": "prod-batfish", "network": "manus-production"},
                    run=run,
                    batfish=batfish,
                )


if __name__ == "__main__":
    unittest.main()

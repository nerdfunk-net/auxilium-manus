"""Tests for workflow_steps.common.batfish_context."""

from __future__ import annotations

import unittest

from models.workflow_context import Capability, DeviceStatus, WorkflowContext
from services.batfish.credentials import BatfishConnection
from workflow_steps.common.batfish_context import (
    devices_from_nodes,
    resolve_batfish_snapshot,
    store_batfish_snapshot,
)


def _context(**metadata) -> WorkflowContext:
    return WorkflowContext(run_id="run-uuid-1", workflow_id="1", metadata=metadata)


class BatfishContextHelperTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        context = _context()
        connection = BatfishConnection(host="batfish", port=9996)

        stored = store_batfish_snapshot(
            context, connection=connection, network="manus-workflow-1", snapshot="run-42"
        )
        ref = resolve_batfish_snapshot(stored)

        self.assertEqual(ref.connection, connection)
        self.assertEqual(ref.network, "manus-workflow-1")
        self.assertEqual(ref.snapshot, "run-42")

    def test_missing_metadata_raises_value_error(self) -> None:
        context = _context()
        with self.assertRaises(ValueError):
            resolve_batfish_snapshot(context)

    def test_malformed_metadata_raises_value_error(self) -> None:
        context = _context(batfish={"host": "batfish", "port": 9996})  # missing network/snapshot
        with self.assertRaises(ValueError):
            resolve_batfish_snapshot(context)

    def test_non_dict_metadata_raises_value_error(self) -> None:
        context = _context(batfish="not-a-dict")
        with self.assertRaises(ValueError):
            resolve_batfish_snapshot(context)


class DevicesFromNodesTests(unittest.TestCase):
    def test_dedupes_by_node(self) -> None:
        devices = devices_from_nodes(
            [{"Node": "r1"}, {"Node": "r1"}, {"Node": "r2"}],
        )

        self.assertEqual(set(devices), {"r1", "r2"})
        device = devices["r1"]
        self.assertEqual(device.id, "r1")
        self.assertEqual(device.name, "r1")
        self.assertEqual(device.hostname, "r1")
        self.assertEqual(device.source, "batfish")
        self.assertEqual(device.capabilities, {Capability.IDENTITY})
        self.assertEqual(device.status, DeviceStatus.OK)

    def test_empty_rows_returns_empty_dict(self) -> None:
        self.assertEqual(devices_from_nodes([]), {})

    def test_skips_rows_with_no_node(self) -> None:
        devices = devices_from_nodes([{"Node": None}, {"Node": ""}, {"Node": "r1"}])
        self.assertEqual(set(devices), {"r1"})


if __name__ == "__main__":
    unittest.main()

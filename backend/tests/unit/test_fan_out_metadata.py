"""Tests for workflow_steps.common.fan_out.build_fan_out_metadata."""

from __future__ import annotations

import unittest

from workflow_steps.common.fan_out import build_fan_out_metadata


class BuildFanOutMetadataTests(unittest.TestCase):
    def test_none_config_returns_none(self) -> None:
        self.assertIsNone(build_fan_out_metadata(None, "node-1"))

    def test_disabled_config_returns_none(self) -> None:
        self.assertIsNone(build_fan_out_metadata({"enabled": False}, "node-1"))

    def test_absent_enabled_key_returns_none(self) -> None:
        self.assertIsNone(build_fan_out_metadata({"mode": "chunked"}, "node-1"))

    def test_defaults_when_only_enabled_is_set(self) -> None:
        result = build_fan_out_metadata({"enabled": True}, "node-1")
        self.assertEqual(
            result,
            {
                "enabled": True,
                "mode": "per_device",
                "chunk_size": 1,
                "max_concurrency": 0,
                "inventory_node_id": "node-1",
                "approval": {
                    "enabled": False,
                    "batch_size": 1,
                    "first_batch_auto": True,
                },
            },
        )

    def test_chunk_size_and_batch_size_clamped_to_minimum_one(self) -> None:
        result = build_fan_out_metadata(
            {
                "enabled": True,
                "chunk_size": 0,
                "approval": {"enabled": True, "batch_size": -5},
            },
            "node-1",
        )
        assert result is not None
        self.assertEqual(result["chunk_size"], 1)
        self.assertEqual(result["approval"]["batch_size"], 1)

    def test_max_concurrency_clamped_to_minimum_zero(self) -> None:
        result = build_fan_out_metadata({"enabled": True, "max_concurrency": -3}, "node-1")
        assert result is not None
        self.assertEqual(result["max_concurrency"], 0)

    def test_approval_passthrough(self) -> None:
        result = build_fan_out_metadata(
            {
                "enabled": True,
                "mode": "chunked",
                "chunk_size": 10,
                "approval": {
                    "enabled": True,
                    "batch_size": 3,
                    "first_batch_auto": False,
                },
            },
            "node-1",
        )
        assert result is not None
        self.assertEqual(
            result["approval"],
            {"enabled": True, "batch_size": 3, "first_batch_auto": False},
        )

    def test_malformed_approval_treated_as_disabled(self) -> None:
        result = build_fan_out_metadata({"enabled": True, "approval": "not-a-dict"}, "node-1")
        assert result is not None
        self.assertEqual(
            result["approval"],
            {"enabled": False, "batch_size": 1, "first_batch_auto": True},
        )


if __name__ == "__main__":
    unittest.main()

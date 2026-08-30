"""Tests for workflow_steps/merge_content/executor.py."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from models.workflow_context import (
    ArtifactRef,
    Capability,
    CommandResult,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from workflow_steps.merge_content.executor import (
    _build_merge_outcomes,
    _merge_items_to_string,
    _parse_content_source,
    _parse_include_command_header,
    _parse_merge_config,
    _parse_merge_mode,
    _parse_source_step_node_ids,
    _partition_device_results,
    execute,
)


class ParseHelperTests(unittest.TestCase):
    def test_content_source_default_and_invalid(self) -> None:
        self.assertEqual(_parse_content_source({}), "command_output")
        with self.assertRaises(ValueError):
            _parse_content_source({"content_source": "bad"})

    def test_source_step_node_ids_forms(self) -> None:
        self.assertEqual(_parse_source_step_node_ids({}), [])
        self.assertEqual(_parse_source_step_node_ids({"source_step_node_ids": "  "}), [])
        self.assertEqual(
            _parse_source_step_node_ids({"source_step_node_ids": '["a", "b"]'}), ["a", "b"]
        )
        self.assertEqual(
            _parse_source_step_node_ids({"source_step_node_ids": "a, b ,c"}), ["a", "b", "c"]
        )
        self.assertEqual(
            _parse_source_step_node_ids({"source_step_node_ids": ["x", "", "y"]}), ["x", "y"]
        )
        self.assertEqual(_parse_source_step_node_ids({"source_step_node_ids": 42}), [])

    def test_merge_mode_default_and_invalid(self) -> None:
        self.assertEqual(_parse_merge_mode({}), "text_sectioned")
        with self.assertRaises(ValueError):
            _parse_merge_mode({"merge_mode": "bogus"})

    def test_include_command_header_coercions(self) -> None:
        self.assertTrue(_parse_include_command_header({}))
        self.assertFalse(_parse_include_command_header({"include_command_header": "false"}))
        self.assertFalse(_parse_include_command_header({"include_command_header": False}))
        self.assertTrue(_parse_include_command_header({"include_command_header": 1}))

    def test_parse_merge_config_requires_node_ids_for_non_command_source(self) -> None:
        with self.assertRaises(ValueError):
            _parse_merge_config({"content_source": "filtered_output"})
        cfg = _parse_merge_config(
            {"content_source": "filtered_output", "source_step_node_ids": ["n1"]}
        )
        self.assertEqual(cfg.source_node_ids, ["n1"])


class MergeItemsToStringTests(unittest.TestCase):
    _ITEMS = [
        ("show ver", "Version 1\n", "text/plain"),
        ("show run", '{"a": 1}', "application/json"),
    ]

    def test_text_sectioned_with_headers(self) -> None:
        cfg = _parse_merge_config({"merge_mode": "text_sectioned"})
        out, media = _merge_items_to_string(items=self._ITEMS, parsed=cfg)
        self.assertIn("=== show ver ===", out)
        self.assertEqual(media, "text/plain")
        self.assertTrue(out.endswith("\n"))

    def test_text_sectioned_without_headers(self) -> None:
        cfg = _parse_merge_config(
            {"merge_mode": "text_sectioned", "include_command_header": "false"}
        )
        out, _ = _merge_items_to_string(items=self._ITEMS, parsed=cfg)
        self.assertNotIn("===", out)

    def test_text_plain_joins_raw_text(self) -> None:
        cfg = _parse_merge_config({"merge_mode": "text_plain"})
        out, media = _merge_items_to_string(items=self._ITEMS, parsed=cfg)
        self.assertNotIn("===", out)
        self.assertEqual(media, "text/plain")

    def test_json_merged_parses_json_and_keeps_text(self) -> None:
        cfg = _parse_merge_config({"merge_mode": "json_merged"})
        items = [
            ("cmdA", '{"k": 2}', "application/json"),
            ("cmdB", "plain text", "text/plain"),
            ("cmdC", "{bad json", "application/json"),
        ]
        out, media = _merge_items_to_string(items=items, parsed=cfg)
        obj = json.loads(out)
        self.assertEqual(obj["cmdA"], {"k": 2})
        self.assertEqual(obj["cmdB"], "plain text")
        self.assertEqual(obj["cmdC"], "{bad json")
        self.assertEqual(media, "application/json")


class PartitionAndOutcomeTests(unittest.TestCase):
    def test_partition(self) -> None:
        d = MagicMock()
        ok, failed = _partition_device_results([("a", d, True), ("b", d, False)])
        self.assertEqual((list(ok), list(failed)), (["a"], ["b"]))

    def test_build_outcomes(self) -> None:
        ctx = WorkflowContext(run_id="r", workflow_id="w", devices={})
        d = MagicMock()
        only_ok = _build_merge_outcomes(
            context=ctx, node_id="n", merge_mode="text_plain",
            success_devices={"a": d}, failed_devices={},
        )
        self.assertEqual([o.name for o in only_ok], ["success"])
        both = _build_merge_outcomes(
            context=ctx, node_id="n", merge_mode="text_plain",
            success_devices={"a": d}, failed_devices={"b": d},
        )
        self.assertEqual([o.name for o in both], ["success", "failure"])
        self.assertEqual(both[0].context.metadata["n.merged_content_mode"], "text_plain")


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    return run


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_devices_returns_success(self) -> None:
        outcomes = await execute(
            config={}, context=WorkflowContext(run_id="r", workflow_id="w", devices={}),
            run=_run(), artifact_service=InMemoryArtifactService(),
            node_id="n", device_sessions=MagicMock(),
        )
        self.assertEqual([o.name for o in outcomes], ["success"])

    async def test_merges_all_command_outputs_for_a_device(self) -> None:
        artifacts = InMemoryArtifactService()
        ref_a = await artifacts.store(
            content="A output\n", kind="command_output", device_id="d1", run_id="run-1"
        )
        ref_b = await artifacts.store(
            content="B output\n", kind="command_output", device_id="d1", run_id="run-1"
        )
        device = DeviceContext(
            id="d1", name="d1", hostname="d1",
            command_results={
                "run-node": [
                    CommandResult(
                        node_id="run-node", command="cmd a", success=True, output_ref=ref_a
                    ),
                    CommandResult(
                        node_id="run-node", command="cmd b", success=True, output_ref=ref_b
                    ),
                    CommandResult(
                        node_id="run-node", command="cmd c", success=False, output_ref=None
                    ),
                ]
            },
            capabilities={Capability.IDENTITY}, status=DeviceStatus.OK,
        )
        outcomes = await execute(
            config={"merge_mode": "text_sectioned"},
            context=WorkflowContext(run_id="run-1", workflow_id="w", devices={"d1": device}),
            run=_run(), artifact_service=artifacts, node_id="merge-1", device_sessions=MagicMock(),
        )
        success = next(o for o in outcomes if o.name == "success")
        enriched = success.context.devices["d1"]
        entry = enriched.parsed["merge-1.merged_content"]
        merged = await artifacts.resolve(ArtifactRef.model_validate(entry["artifact_ref"]))
        self.assertIn("=== cmd a ===", merged)
        self.assertIn("=== cmd b ===", merged)
        self.assertIn(Capability.PARSED, enriched.capabilities)

    async def test_non_command_source_without_content_produces_empty_merge(self) -> None:
        device = DeviceContext(
            id="d1", name="d1", hostname="d1",
            capabilities={Capability.IDENTITY}, status=DeviceStatus.OK,
        )
        outcomes = await execute(
            config={"content_source": "filtered_output", "source_step_node_ids": ["f-1"]},
            context=WorkflowContext(run_id="run-1", workflow_id="w", devices={"d1": device}),
            run=_run(), artifact_service=InMemoryArtifactService(),
            node_id="merge-1", device_sessions=MagicMock(),
        )
        # no source content -> empty string still stored, device succeeds
        self.assertEqual({o.name for o in outcomes}, {"success"})


if __name__ == "__main__":
    unittest.main()

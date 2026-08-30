"""Tests for workflow_steps/filter_output/executor.py."""

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
from workflow_steps.filter_output.executor import (
    _apply_path_rule,
    _apply_pattern_rules,
    _build_filter_outcomes,
    _filter_json,
    _filter_text,
    _parse_filter_config,
    _parse_filter_rules,
    _partition_device_results,
    _select_export_item,
    execute,
)


class ParseRulesTests(unittest.TestCase):
    def test_empty_rules_returns_empty_list(self) -> None:
        self.assertEqual(_parse_filter_rules({}), [])

    def test_non_list_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_filter_rules({"filter_rules": "x"})

    def test_item_not_dict_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_filter_rules({"filter_rules": ["x"]})

    def test_item_without_pattern_or_path_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_filter_rules({"filter_rules": [{}]})

    def test_invalid_regex_pattern_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_filter_rules({"filter_rules": [{"pattern": "("}]})

    def test_pattern_and_path_rules(self) -> None:
        rules = _parse_filter_rules(
            {"filter_rules": [{"pattern": "uptime"}, {"path": "a.b"}]}
        )
        self.assertEqual(rules, [
            {"type": "pattern", "value": "uptime"},
            {"type": "path", "value": "a.b"},
        ])


class ParseConfigTests(unittest.TestCase):
    def test_bad_content_source_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_filter_config({"content_source": "bogus", "source_step_node_id": "n"})

    def test_missing_node_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_filter_config({"filter_rules": [{"pattern": "x"}]})

    def test_no_rules_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_filter_config({"source_step_node_id": "n"})

    def test_valid_config(self) -> None:
        cfg = _parse_filter_config(
            {"source_step_node_id": "n", "filter_rules": [{"pattern": "x"}]}
        )
        self.assertEqual(cfg.content_source, "command_output")
        self.assertEqual(cfg.source_step_node_id, "n")


class FilterHelperTests(unittest.TestCase):
    def test_apply_pattern_rules_removes_matching_keys_recursively(self) -> None:
        data = {"uptime": 1, "keep": {"uptime_secs": 2, "value": 3}, "list": [{"uptime": 4}]}
        self.assertEqual(
            _apply_pattern_rules(data, ["uptime"]),
            {"keep": {"value": 3}, "list": [{}]},
        )

    def test_apply_path_rule_removes_leaf(self) -> None:
        data = {"route": {"ospf": 1, "bgp": 2}}
        self.assertEqual(_apply_path_rule(data, ["route", "ospf"]), {"route": {"bgp": 2}})

    def test_apply_path_rule_on_list(self) -> None:
        data = [{"a": {"b": 1}}, {"a": {"b": 2, "c": 3}}]
        self.assertEqual(
            _apply_path_rule(data, ["a", "b"]), [{"a": {}}, {"a": {"c": 3}}]
        )

    def test_filter_json_combines_pattern_and_path(self) -> None:
        data = {"uptime": 1, "route": {"ospf": {"pid": 9}}, "keep": 2}
        out = _filter_json(data, [
            {"type": "pattern", "value": "uptime"},
            {"type": "path", "value": "route.ospf"},
        ])
        self.assertEqual(out, {"route": {}, "keep": 2})

    def test_filter_text_drops_matching_lines(self) -> None:
        text = "uptime is 5 days\nhostname lab\nuptime counter 3\n"
        self.assertEqual(_filter_text(text, [{"type": "pattern", "value": "uptime"}]),
                         "hostname lab\n")

    def test_filter_text_without_pattern_is_identity(self) -> None:
        self.assertEqual(_filter_text("abc", [{"type": "path", "value": "x"}]), "abc")


class SelectAndPartitionTests(unittest.TestCase):
    def _item(self, command: str) -> MagicMock:
        item = MagicMock()
        item.extra = {"command": command}
        return item

    def test_select_by_command(self) -> None:
        cfg = _parse_filter_config(
            {"source_step_node_id": "n", "source_command": "show run",
             "filter_rules": [{"pattern": "x"}]}
        )
        items = [self._item("show ver"), self._item("show run")]
        self.assertIs(_select_export_item(items, parsed=cfg), items[1])

    def test_select_command_not_found_raises(self) -> None:
        cfg = _parse_filter_config(
            {"source_step_node_id": "n", "source_command": "missing",
             "filter_rules": [{"pattern": "x"}]}
        )
        with self.assertRaises(ValueError):
            _select_export_item([self._item("show ver")], parsed=cfg)

    def test_select_defaults_to_first(self) -> None:
        cfg = _parse_filter_config(
            {"source_step_node_id": "n", "filter_rules": [{"pattern": "x"}]}
        )
        items = [self._item("a"), self._item("b")]
        self.assertIs(_select_export_item(items, parsed=cfg), items[0])

    def test_partition_splits_ok_and_failed(self) -> None:
        d = MagicMock()
        ok, failed = _partition_device_results([("a", d, True), ("b", d, False)])
        self.assertEqual(list(ok), ["a"])
        self.assertEqual(list(failed), ["b"])

    def test_build_outcomes_success_only_and_with_failure(self) -> None:
        ctx = WorkflowContext(run_id="r", workflow_id="w", devices={})
        d = MagicMock()
        only_success = _build_filter_outcomes(
            context=ctx, node_id="n", success_devices={"a": d}, failed_devices={}
        )
        self.assertEqual([o.name for o in only_success], ["success"])
        with_failure = _build_filter_outcomes(
            context=ctx, node_id="n", success_devices={"a": d}, failed_devices={"b": d}
        )
        self.assertEqual([o.name for o in with_failure], ["success", "failure"])


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    return run


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def _device_with_command_output(
        self, artifacts: InMemoryArtifactService, content: str, media_type: str
    ) -> DeviceContext:
        ref = await artifacts.store(
            content=content, kind="command_output", device_id="d1", run_id="run-1",
            media_type=media_type,
        )
        return DeviceContext(
            id="d1", name="d1", hostname="d1",
            command_results={
                "src-node": [
                    CommandResult(
                        node_id="src-node", command="show json", success=True,
                        output_ref=ref,
                    )
                ]
            },
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )

    async def test_empty_devices_returns_single_success(self) -> None:
        outcomes = await execute(
            config={"source_step_node_id": "n", "filter_rules": [{"pattern": "x"}]},
            context=WorkflowContext(run_id="r", workflow_id="w", devices={}),
            run=_run(), artifact_service=InMemoryArtifactService(),
            node_id="node-1", device_sessions=MagicMock(),
        )
        self.assertEqual([o.name for o in outcomes], ["success"])

    async def test_json_content_is_filtered_and_stored(self) -> None:
        artifacts = InMemoryArtifactService()
        payload = json.dumps({"uptime": 100, "hostname": "lab", "nested": {"uptime": 1}})
        device = await self._device_with_command_output(artifacts, payload, "application/json")

        outcomes = await execute(
            config={
                "content_source": "command_output",
                "source_step_node_id": "src-node",
                "filter_rules": [{"pattern": "uptime"}],
            },
            context=WorkflowContext(run_id="run-1", workflow_id="w", devices={"d1": device}),
            run=_run(), artifact_service=artifacts, node_id="node-1", device_sessions=MagicMock(),
        )
        success = next(o for o in outcomes if o.name == "success")
        enriched = success.context.devices["d1"]
        entry = enriched.parsed["node-1.filtered_output"]
        stored = await artifacts.resolve(ArtifactRef.model_validate(entry["artifact_ref"]))
        self.assertNotIn("uptime", stored)
        self.assertIn("hostname", stored)
        self.assertIn(Capability.PARSED, enriched.capabilities)

    async def test_text_content_filtered_by_line(self) -> None:
        artifacts = InMemoryArtifactService()
        text = "uptime 5 days\nhostname lab\n"
        device = await self._device_with_command_output(artifacts, text, "text/plain")
        outcomes = await execute(
            config={
                "content_source": "command_output",
                "source_step_node_id": "src-node",
                "filter_rules": [{"pattern": "uptime"}],
            },
            context=WorkflowContext(run_id="run-1", workflow_id="w", devices={"d1": device}),
            run=_run(), artifact_service=artifacts, node_id="node-1", device_sessions=MagicMock(),
        )
        self.assertEqual({o.name for o in outcomes}, {"success"})

    async def test_device_without_source_content_routes_to_failure(self) -> None:
        device = DeviceContext(
            id="d1", name="d1", hostname="d1",
            capabilities={Capability.IDENTITY}, status=DeviceStatus.OK,
        )
        outcomes = await execute(
            config={
                "content_source": "command_output",
                "source_step_node_id": "src-node",
                "filter_rules": [{"pattern": "x"}],
            },
            context=WorkflowContext(run_id="run-1", workflow_id="w", devices={"d1": device}),
            run=_run(), artifact_service=InMemoryArtifactService(),
            node_id="node-1", device_sessions=MagicMock(),
        )
        by_name = {o.name: o for o in outcomes}
        self.assertIn("failure", by_name)
        self.assertEqual(list(by_name["failure"].context.devices), ["d1"])
        self.assertEqual(by_name["success"].context.devices, {})


if __name__ == "__main__":
    unittest.main()

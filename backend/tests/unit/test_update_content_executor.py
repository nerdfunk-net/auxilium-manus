"""Tests for workflow_steps/update_content/executor.py."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from models.workflow_context import (
    ArtifactRef,
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from workflow_steps.update_content.executor import (
    _apply_rules_to_text,
    _build_update_content_outcomes,
    _parse_content_source,
    _parse_replace_all,
    _parse_rules,
    _parse_update_content_config,
    _partition_device_results,
    _source_ref,
    execute,
)


class ParseHelperTests(unittest.TestCase):
    def test_content_source_default_and_invalid(self) -> None:
        self.assertEqual(_parse_content_source({}), "running_config")
        with self.assertRaises(ValueError):
            _parse_content_source({"content_source": "command_output"})

    def test_parse_replace_all(self) -> None:
        self.assertTrue(_parse_replace_all(None))
        self.assertTrue(_parse_replace_all(True))
        self.assertFalse(_parse_replace_all(False))
        self.assertFalse(_parse_replace_all("off"))
        self.assertTrue(_parse_replace_all("yes"))
        self.assertTrue(_parse_replace_all(1))

    def test_parse_rules_requires_a_list_of_dicts_with_patterns(self) -> None:
        with self.assertRaises(ValueError):
            _parse_rules({})
        with self.assertRaises(ValueError):
            _parse_rules({"replace_rules": "x"})
        with self.assertRaises(ValueError):
            _parse_rules({"replace_rules": ["x"]})
        with self.assertRaises(ValueError):
            _parse_rules({"replace_rules": [{"pattern": " "}]})

    def test_parse_rules_builds_replace_rule(self) -> None:
        rules = _parse_rules(
            {"replace_rules": [
                {"pattern": "secret \\S+", "replacement": "secret ***", "replace_all": "false"},
            ]}
        )
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].replacement, "secret ***")
        self.assertFalse(rules[0].replace_all)

    def test_parse_config_combines_source_and_rules(self) -> None:
        cfg = _parse_update_content_config(
            {"content_source": "startup_config", "replace_rules": [{"pattern": "a"}]}
        )
        self.assertEqual(cfg.content_source, "startup_config")
        self.assertEqual(len(cfg.rules), 1)


class ApplyRulesTests(unittest.TestCase):
    def test_apply_rules_in_order_with_match_counts(self) -> None:
        rules = _parse_rules(
            {"replace_rules": [
                {"pattern": "foo", "replacement": "bar"},
                {"pattern": "bar", "replacement": "baz"},
            ]}
        )
        out, counts = _apply_rules_to_text("foo foo\n", rules)
        self.assertEqual(out, "baz baz\n")
        self.assertEqual(counts, [2, 2])


class SourceRefTests(unittest.TestCase):
    def test_source_ref_selects_running_or_startup(self) -> None:
        rc = ArtifactRef(artifact_id="rc", kind="running_config")
        sc = ArtifactRef(artifact_id="sc", kind="startup_config")
        device = DeviceContext(
            id="d1", name="d1", hostname="d1", status=DeviceStatus.OK,
            running_config_ref=rc, startup_config_ref=sc,
        )
        self.assertEqual(_source_ref(device, "running_config").artifact_id, "rc")
        self.assertEqual(_source_ref(device, "startup_config").artifact_id, "sc")


class PartitionAndOutcomeTests(unittest.TestCase):
    def test_partition_and_outcomes(self) -> None:
        d = MagicMock()
        ok, failed = _partition_device_results([("a", d, True), ("b", d, False)])
        self.assertEqual((list(ok), list(failed)), (["a"], ["b"]))
        ctx = WorkflowContext(run_id="r", workflow_id="w", devices={})
        outs = _build_update_content_outcomes(
            context=ctx, node_id="n", success_devices={"a": d}, failed_devices={"b": d}
        )
        self.assertEqual([o.name for o in outs], ["success", "failure"])


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    return run


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_devices_returns_success(self) -> None:
        outcomes = await execute(
            config={"replace_rules": [{"pattern": "x"}]},
            context=WorkflowContext(run_id="r", workflow_id="w", devices={}),
            run=_run(), artifact_service=InMemoryArtifactService(),
            node_id="n", device_sessions=MagicMock(),
        )
        self.assertEqual([o.name for o in outcomes], ["success"])

    async def test_rewrites_running_config_and_stores_updated_content(self) -> None:
        artifacts = InMemoryArtifactService()
        ref = await artifacts.store(
            content="username admin secret CLEARTEXT\n", kind="running_config",
            device_id="d1", run_id="run-1",
        )
        device = DeviceContext(
            id="d1", name="d1", hostname="d1", status=DeviceStatus.OK,
            running_config_ref=ref, capabilities={Capability.IDENTITY},
        )
        outcomes = await execute(
            config={"replace_rules": [{"pattern": "secret \\S+", "replacement": "secret ***"}]},
            context=WorkflowContext(run_id="run-1", workflow_id="w", devices={"d1": device}),
            run=_run(), artifact_service=artifacts, node_id="uc-1", device_sessions=MagicMock(),
        )
        success = next(o for o in outcomes if o.name == "success")
        entry = success.context.devices["d1"].parsed["uc-1.updated_content"]
        updated = await artifacts.resolve(ArtifactRef.model_validate(entry["artifact_ref"]))
        self.assertIn("secret ***", updated)
        self.assertEqual(entry["match_counts"], [1])

    async def test_missing_source_config_routes_to_failure(self) -> None:
        device = DeviceContext(
            id="d1", name="d1", hostname="d1", status=DeviceStatus.OK,
            capabilities={Capability.IDENTITY},
        )
        outcomes = await execute(
            config={"replace_rules": [{"pattern": "x"}]},
            context=WorkflowContext(run_id="run-1", workflow_id="w", devices={"d1": device}),
            run=_run(), artifact_service=InMemoryArtifactService(),
            node_id="uc-1", device_sessions=MagicMock(),
        )
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["failure"].context.devices), ["d1"])


if __name__ == "__main__":
    unittest.main()

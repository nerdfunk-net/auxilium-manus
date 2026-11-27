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
from tests.unit._step_helpers import make_run
from workflow_steps.common.regex_search import replace_many
from workflow_steps.update_content.executor import (
    _parse_rules,
    _parse_update_content_config,
    _source_ref,
    execute,
)

_RULE = {"replace_rules": [{"pattern": "x"}]}
_MISSING = object()


class ParseHelperTests(unittest.TestCase):
    def test_content_source_default_and_invalid(self) -> None:
        self.assertEqual(_parse_update_content_config(_RULE).content_source, "running_config")
        with self.assertRaises(ValueError):
            _parse_update_content_config({**_RULE, "content_source": "command_output"})

    def test_parse_replace_all(self) -> None:
        def replace_all(value: object) -> bool:
            rule: dict = {"pattern": "a", "replacement": "b"}
            if value is not _MISSING:
                rule["replace_all"] = value
            return _parse_rules({"replace_rules": [rule]})[0].replace_all

        self.assertTrue(replace_all(_MISSING))
        self.assertTrue(replace_all(None))
        self.assertTrue(replace_all(True))
        self.assertFalse(replace_all(False))
        self.assertFalse(replace_all("off"))
        self.assertTrue(replace_all("yes"))
        self.assertTrue(replace_all(1))

    def test_replace_all_typo_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "replace_all must be true or false"):
            _parse_rules({"replace_rules": [{"pattern": "a", "replace_all": "nope"}]})

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
            {
                "replace_rules": [
                    {"pattern": "secret \\S+", "replacement": "secret ***", "replace_all": "false"},
                ]
            }
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


class ApplyRulesTests(unittest.IsolatedAsyncioTestCase):
    async def test_apply_rules_in_order_with_match_counts(self) -> None:
        rules = _parse_rules(
            {
                "replace_rules": [
                    {"pattern": "foo", "replacement": "bar"},
                    {"pattern": "bar", "replacement": "baz"},
                ]
            }
        )
        out, counts = await replace_many("foo foo\n", rules)
        self.assertEqual(out, "baz baz\n")
        self.assertEqual(counts, [2, 2])


class SourceRefTests(unittest.TestCase):
    def test_source_ref_selects_running_or_startup(self) -> None:
        rc = ArtifactRef(artifact_id="rc", kind="running_config")
        sc = ArtifactRef(artifact_id="sc", kind="startup_config")
        device = DeviceContext(
            id="d1",
            name="d1",
            hostname="d1",
            status=DeviceStatus.OK,
            running_config_ref=rc,
            startup_config_ref=sc,
        )
        self.assertEqual(_source_ref(device, "running_config").artifact_id, "rc")
        self.assertEqual(_source_ref(device, "startup_config").artifact_id, "sc")


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_devices_returns_success(self) -> None:
        outcomes = await execute(
            config={"replace_rules": [{"pattern": "x"}]},
            context=WorkflowContext(run_id="r", workflow_id="w", devices={}),
            run=make_run(),
            artifact_service=InMemoryArtifactService(),
            node_id="n",
            device_sessions=MagicMock(),
        )
        self.assertEqual([o.name for o in outcomes], ["success"])

    async def test_rewrites_running_config_and_stores_updated_content(self) -> None:
        artifacts = InMemoryArtifactService()
        ref = await artifacts.store(
            content="username admin secret CLEARTEXT\n",
            kind="running_config",
            device_id="d1",
            run_id="run-1",
        )
        device = DeviceContext(
            id="d1",
            name="d1",
            hostname="d1",
            status=DeviceStatus.OK,
            running_config_ref=ref,
            capabilities={Capability.IDENTITY},
        )
        outcomes = await execute(
            config={"replace_rules": [{"pattern": "secret \\S+", "replacement": "secret ***"}]},
            context=WorkflowContext(run_id="run-1", workflow_id="w", devices={"d1": device}),
            run=make_run(),
            artifact_service=artifacts,
            node_id="uc-1",
            device_sessions=MagicMock(),
        )
        success = next(o for o in outcomes if o.name == "success")
        entry = success.context.devices["d1"].parsed["uc-1"]["updated_content"]
        updated = await artifacts.resolve(ArtifactRef.model_validate(entry["artifact_ref"]))
        self.assertIn("secret ***", updated)
        self.assertEqual(entry["match_counts"], [1])

    async def test_the_rules_go_to_the_isolated_worker(self) -> None:
        # S4-07 (was W4-15, off the loop): the step never runs the author's regex itself.
        from unittest.mock import AsyncMock, patch

        isolated = AsyncMock(return_value=("b\n", [1]))

        artifacts = InMemoryArtifactService()
        ref = await artifacts.store(
            content="a\n", kind="running_config", device_id="d1", run_id="run-1"
        )
        device = DeviceContext(
            id="d1",
            name="d1",
            hostname="d1",
            status=DeviceStatus.OK,
            running_config_ref=ref,
            capabilities={Capability.IDENTITY},
        )
        with patch("workflow_steps.update_content.executor.replace_many", isolated):
            await execute(
                config={"replace_rules": [{"pattern": "a", "replacement": "b"}]},
                context=WorkflowContext(run_id="run-1", workflow_id="w", devices={"d1": device}),
                run=make_run(),
                artifact_service=artifacts,
                node_id="uc-1",
                device_sessions=MagicMock(),
            )
        isolated.assert_awaited_once()
        text, rules = isolated.await_args.args
        self.assertEqual(text, "a\n")
        self.assertEqual([(r.pattern, r.replacement) for r in rules], [("a", "b")])

    async def test_missing_source_config_routes_to_failure(self) -> None:
        device = DeviceContext(
            id="d1",
            name="d1",
            hostname="d1",
            status=DeviceStatus.OK,
            capabilities={Capability.IDENTITY},
        )
        outcomes = await execute(
            config={"replace_rules": [{"pattern": "x"}]},
            context=WorkflowContext(run_id="run-1", workflow_id="w", devices={"d1": device}),
            run=make_run(),
            artifact_service=InMemoryArtifactService(),
            node_id="uc-1",
            device_sessions=MagicMock(),
        )
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["failure"].context.devices), ["d1"])

    async def _no_match_run(self, extra: dict) -> list:
        artifacts = InMemoryArtifactService()
        ref = await artifacts.store(
            content="ntp server 10.0.0.1\n", kind="running_config", device_id="d1", run_id="run-1"
        )
        device = DeviceContext(
            id="d1",
            name="d1",
            hostname="d1",
            status=DeviceStatus.OK,
            running_config_ref=ref,
            capabilities={Capability.IDENTITY},
        )
        return await execute(
            config={"replace_rules": [{"pattern": "typo-pattern", "replacement": "x"}], **extra},
            context=WorkflowContext(run_id="run-1", workflow_id="w", devices={"d1": device}),
            run=make_run(),
            artifact_service=artifacts,
            node_id="uc-1",
            device_sessions=MagicMock(),
        )

    async def test_fail_if_no_match(self) -> None:
        outcomes = await self._no_match_run({"fail_if_no_match": True})
        by_name = {o.name: o for o in outcomes}
        error = by_name["failure"].context.devices["d1"].errors[-1]
        self.assertEqual(error.code, "no_rule_matched")
        self.assertNotIn("d1", by_name["success"].context.devices)

    async def test_no_match_is_not_an_error_by_default(self) -> None:
        for extra in ({}, {"fail_if_no_match": "false"}):
            outcomes = await self._no_match_run(extra)
            by_name = {o.name: o for o in outcomes}
            self.assertIn("d1", by_name["success"].context.devices)

    async def test_non_value_errors_do_not_leak_driver_text(self) -> None:
        from unittest.mock import AsyncMock

        artifacts = InMemoryArtifactService()
        ref = await artifacts.store(
            content="x\n", kind="running_config", device_id="d1", run_id="run-1"
        )
        device = DeviceContext(
            id="d1",
            name="d1",
            hostname="d1",
            status=DeviceStatus.OK,
            running_config_ref=ref,
            capabilities={Capability.IDENTITY},
        )
        artifacts.resolve = AsyncMock(side_effect=RuntimeError("INSERT ... password=hunter2"))  # type: ignore[method-assign]
        outcomes = await execute(
            config={"replace_rules": [{"pattern": "x"}]},
            context=WorkflowContext(run_id="run-1", workflow_id="w", devices={"d1": device}),
            run=make_run(),
            artifact_service=artifacts,
            node_id="uc-1",
            device_sessions=MagicMock(),
        )
        error = next(o for o in outcomes if o.name == "failure").context.devices["d1"].errors[-1]
        self.assertEqual(error.message, "RuntimeError")
        self.assertNotIn("hunter2", str(error))


if __name__ == "__main__":
    unittest.main()

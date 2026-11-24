"""Tests for route-on-content executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from workflow_steps.common.regex_search import RegexAnswer
from workflow_steps.route_on_content.executor import _parse_route_config, execute


async def _device_with_config(
    artifact_service: InMemoryArtifactService,
    *,
    device_id: str,
    content: str,
    attribute_bags: dict | None = None,
) -> DeviceContext:
    ref = await artifact_service.store(
        content=content,
        kind="running_config",
        device_id=device_id,
        run_id="run-uuid-1",
    )
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        attribute_bags=attribute_bags or {},
        running_config_ref=ref,
        capabilities={Capability.IDENTITY, Capability.RUNNING_CONFIG},
        status=DeviceStatus.OK,
    )


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    return run


class RouteOnContentExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_devices_returns_all_outcomes_empty(self) -> None:
        outcomes = await execute(
            config={"pattern": "tacacs-server"},
            context=WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={}),
            run=_run(),
            artifact_service=InMemoryArtifactService(),
            node_id="route-on-content-1",
            device_sessions=MagicMock(),
        )
        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(set(by_name), {"match", "mismatch", "failure"})
        for outcome in outcomes:
            self.assertEqual(outcome.context.devices, {})

    async def test_store_matched_text_keeps_the_match_redacted(self) -> None:
        artifact_service = InMemoryArtifactService()
        device = await _device_with_config(
            artifact_service,
            device_id="d1",
            content="tacacs-server key 7 094F471A1A0A\nhostname r1\n",
        )
        base = {"content_source": "running_config", "match_mode": "regex"}
        for pattern, expected in (
            (r"tacacs-server key \S+ \S+", "tacacs-server key 7 __SECRET_1__"),
            (r"hostname \S+", "hostname r1"),
        ):
            outcomes = await execute(
                config={**base, "pattern": pattern, "store_matched_text": True},
                context=WorkflowContext(run_id="r", workflow_id="w", devices={"d1": device}),
                run=_run(),
                artifact_service=artifact_service,
                node_id="n",
                device_sessions=MagicMock(),
            )
            entry = next(o for o in outcomes if o.name == "match").context.devices["d1"]
            self.assertEqual(entry.parsed["n"]["content_match"]["matched_text"], expected)

    async def test_store_matched_text_must_be_a_boolean(self) -> None:
        with self.assertRaises(ValueError):
            _parse_route_config({"pattern": "x", "store_matched_text": "banana"})

    async def test_fixed_text_match_and_mismatch(self) -> None:
        artifact_service = InMemoryArtifactService()
        matching = await _device_with_config(
            artifact_service, device_id="dev-new", content="tacacs server TACACS_SERVER_NAME\n"
        )
        non_matching = await _device_with_config(
            artifact_service,
            device_id="dev-old",
            content="tacacs-server host 10.0.0.5 key secret\n",
        )

        outcomes = await execute(
            config={
                "content_source": "running_config",
                "match_mode": "fixed_text",
                "pattern": "tacacs server",
            },
            context=WorkflowContext(
                run_id="run-1",
                workflow_id="wf-1",
                devices={"dev-new": matching, "dev-old": non_matching},
            ),
            run=_run(),
            artifact_service=artifact_service,
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["match"].context.devices), ["dev-new"])
        self.assertEqual(list(by_name["mismatch"].context.devices), ["dev-old"])
        self.assertEqual(by_name["failure"].context.devices, {})

        match_entry = by_name["match"].context.devices["dev-new"].parsed["node-1"]["content_match"]
        self.assertTrue(match_entry["matched"])
        # W10-02: the matched text is not stored unless the author asks for it.
        self.assertNotIn("matched_text", match_entry)

        counts = by_name["match"].context.metadata["node-1.content_match_counts"]
        self.assertEqual(counts, {"match": 1, "mismatch": 1, "failure": 0})

    async def test_case_sensitivity(self) -> None:
        artifact_service = InMemoryArtifactService()
        device = await _device_with_config(
            artifact_service, device_id="dev-1", content="Tacacs Server foo\n"
        )

        outcomes_insensitive = await execute(
            config={
                "match_mode": "fixed_text",
                "pattern": "tacacs server",
                "case_sensitive": False,
            },
            context=WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"dev-1": device}),
            run=_run(),
            artifact_service=artifact_service,
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        by_name = {o.name: o for o in outcomes_insensitive}
        self.assertEqual(list(by_name["match"].context.devices), ["dev-1"])

        outcomes_sensitive = await execute(
            config={"match_mode": "fixed_text", "pattern": "tacacs server", "case_sensitive": True},
            context=WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"dev-1": device}),
            run=_run(),
            artifact_service=artifact_service,
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        by_name_sensitive = {o.name: o for o in outcomes_sensitive}
        self.assertEqual(list(by_name_sensitive["mismatch"].context.devices), ["dev-1"])

    async def test_regex_multiline_matches_line_anchor(self) -> None:
        artifact_service = InMemoryArtifactService()
        device = await _device_with_config(
            artifact_service,
            device_id="dev-1",
            content="hostname lab\ntacacs-server host 10.0.0.5 key secret\nend\n",
        )

        outcomes = await execute(
            config={
                "match_mode": "regex",
                "pattern": r"^tacacs-server",
                "multiline": True,
            },
            context=WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"dev-1": device}),
            run=_run(),
            artifact_service=artifact_service,
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["match"].context.devices), ["dev-1"])

    async def test_regex_without_multiline_does_not_anchor_per_line(self) -> None:
        artifact_service = InMemoryArtifactService()
        device = await _device_with_config(
            artifact_service,
            device_id="dev-1",
            content="hostname lab\ntacacs-server host 10.0.0.5 key secret\nend\n",
        )

        outcomes = await execute(
            config={
                "match_mode": "regex",
                "pattern": r"^tacacs-server",
                "multiline": False,
            },
            context=WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"dev-1": device}),
            run=_run(),
            artifact_service=artifact_service,
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["mismatch"].context.devices), ["dev-1"])

    async def test_placeholder_substitution_in_fixed_text(self) -> None:
        artifact_service = InMemoryArtifactService()
        device = await _device_with_config(
            artifact_service,
            device_id="dev-1",
            content="tacacs-server host 10.0.0.5 key secret\n",
            attribute_bags={"custom": {"expected_ip": "10.0.0.5"}},
        )

        outcomes = await execute(
            config={
                "match_mode": "fixed_text",
                "pattern": "tacacs-server host {custom.expected_ip}",
            },
            context=WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"dev-1": device}),
            run=_run(),
            artifact_service=artifact_service,
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["match"].context.devices), ["dev-1"])

    async def test_regex_escapes_substituted_placeholder_values(self) -> None:
        """A resolved attribute value containing regex metacharacters (e.g. the
        dots in an IP address) must be escaped before being spliced into the
        regex, or '.' would wrongly match any character."""
        artifact_service = InMemoryArtifactService()
        # Contains "10a0a0a5" (dots replaced by any char) but NOT the literal
        # "10.0.0.5" — only an unescaped "." would make this match.
        device = await _device_with_config(
            artifact_service,
            device_id="dev-1",
            content="tacacs-server host 10a0a0a5 key secret\n",
            attribute_bags={"custom": {"expected_ip": "10.0.0.5"}},
        )

        outcomes = await execute(
            config={
                "match_mode": "regex",
                "pattern": r"host {custom.expected_ip} key",
            },
            context=WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"dev-1": device}),
            run=_run(),
            artifact_service=artifact_service,
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["mismatch"].context.devices), ["dev-1"])

    async def test_missing_content_routes_to_failure(self) -> None:
        device = DeviceContext(
            id="dev-1",
            name="dev-1",
            hostname="dev-1",
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        outcomes = await execute(
            config={"content_source": "running_config", "pattern": "tacacs"},
            context=WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"dev-1": device}),
            run=_run(),
            artifact_service=InMemoryArtifactService(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["failure"].context.devices), ["dev-1"])
        error = by_name["failure"].context.devices["dev-1"].errors[0]
        self.assertEqual(error.code, "missing_content")
        self.assertEqual(error.failure.kind, "not_found")

    async def test_a_catastrophic_pattern_fails_only_its_device_and_does_not_stall(self) -> None:
        # W10-06: the author's regex runs in the isolated worker, with a time limit.
        import time

        artifact_service = InMemoryArtifactService()
        slow = await _device_with_config(
            artifact_service, device_id="slow", content="a" * 40 + "!\n"
        )
        quick = await _device_with_config(artifact_service, device_id="quick", content="ok\n")
        started = time.monotonic()
        outcomes = await execute(
            config={"match_mode": "regex", "pattern": "(a+)+$"},
            context=WorkflowContext(
                run_id="run-1", workflow_id="wf-1", devices={"slow": slow, "quick": quick}
            ),
            run=_run(),
            artifact_service=artifact_service,
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        self.assertLess(time.monotonic() - started, 5)
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["failure"].context.devices), ["slow"])
        error = by_name["failure"].context.devices["slow"].errors[0]
        self.assertEqual(error.code, "regex_stopped")
        self.assertEqual(error.failure.kind, "bad_request")
        self.assertEqual(list(by_name["mismatch"].context.devices), ["quick"])

    async def test_regex_matching_goes_through_the_isolated_search(self) -> None:
        artifact_service = InMemoryArtifactService()
        device = await _device_with_config(
            artifact_service, device_id="dev-1", content="line\ntacacs-server host 10.0.0.5\n"
        )
        seen: list[object] = []

        async def fake_search(questions, **kwargs):
            seen.append((list(questions), kwargs))
            return [RegexAnswer(status="match", match="tacacs-server host")]

        with patch(
            "workflow_steps.route_on_content.executor.search_many", fake_search
        ):
            outcomes = await execute(
                config={
                    "match_mode": "regex",
                    "pattern": "tacacs-server host",
                    "multiline": True,
                    "case_sensitive": True,
                },
                context=WorkflowContext(
                    run_id="run-1", workflow_id="wf-1", devices={"dev-1": device}
                ),
                run=_run(),
                artifact_service=artifact_service,
                node_id="node-1",
                device_sessions=MagicMock(),
            )
        (questions, kwargs), = seen
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0].pattern, "tacacs-server host")
        self.assertIn("tacacs-server", questions[0].text)
        self.assertEqual(kwargs["ignore_case"], False)
        self.assertEqual(kwargs["multiline"], True)
        self.assertEqual(
            [o.name for o in outcomes if o.context.devices], ["match"]
        )

    async def test_invalid_regex_routes_to_failure(self) -> None:
        artifact_service = InMemoryArtifactService()
        device = await _device_with_config(
            artifact_service, device_id="dev-1", content="tacacs-server host 10.0.0.5\n"
        )
        outcomes = await execute(
            config={"match_mode": "regex", "pattern": "tacacs-server("},
            context=WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"dev-1": device}),
            run=_run(),
            artifact_service=artifact_service,
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["failure"].context.devices), ["dev-1"])
        error = by_name["failure"].context.devices["dev-1"].errors[0]
        self.assertEqual(error.code, "invalid_regex")
        self.assertEqual(error.failure.kind, "bad_request")

    async def test_pattern_resolving_to_empty_string_routes_to_failure(self) -> None:
        artifact_service = InMemoryArtifactService()
        device = await _device_with_config(
            artifact_service, device_id="dev-1", content="tacacs-server host 10.0.0.5\n"
        )
        outcomes = await execute(
            config={"match_mode": "fixed_text", "pattern": "{custom.missing_path}"},
            context=WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"dev-1": device}),
            run=_run(),
            artifact_service=artifact_service,
            node_id="node-1",
            device_sessions=MagicMock(),
        )
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["failure"].context.devices), ["dev-1"])
        error = by_name["failure"].context.devices["dev-1"].errors[0]
        self.assertEqual(error.code, "pattern_unresolved")
        self.assertEqual(error.failure.kind, "bad_request")

    async def test_missing_pattern_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            await execute(
                config={"pattern": ""},
                context=WorkflowContext(
                    run_id="run-1",
                    workflow_id="wf-1",
                    devices={
                        "dev-1": DeviceContext(
                            id="dev-1", name="dev-1", hostname="dev-1", status=DeviceStatus.OK
                        )
                    },
                ),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_invalid_match_mode_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            await execute(
                config={"pattern": "tacacs", "match_mode": "bogus"},
                context=WorkflowContext(
                    run_id="run-1",
                    workflow_id="wf-1",
                    devices={
                        "dev-1": DeviceContext(
                            id="dev-1", name="dev-1", hostname="dev-1", status=DeviceStatus.OK
                        )
                    },
                ),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_multiple_command_outputs_fail_the_device(self) -> None:
        from models.workflow_context import CommandResult

        artifact_service = InMemoryArtifactService()
        refs = [
            await artifact_service.store(
                content=text, kind="command_output", device_id="dev-1", run_id="run-uuid-1"
            )
            for text in ("one\n", "two\n")
        ]
        device = DeviceContext(
            id="dev-1",
            name="dev-1",
            hostname="dev-1",
            command_results={
                "run-1": [
                    CommandResult(
                        node_id="run-1", command="show a", success=True, output_ref=refs[0]
                    ),
                    CommandResult(
                        node_id="run-1", command="show b", success=True, output_ref=refs[1]
                    ),
                ]
            },
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        outcomes = await execute(
            config={
                "content_source": "command_output",
                "source_step_node_id": "run-1",
                "match_mode": "fixed_text",
                "pattern": "one",
            },
            context=WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"dev-1": device}),
            run=_run(),
            artifact_service=artifact_service,
            node_id="route-1",
            device_sessions=MagicMock(),
        )
        by_name = {o.name: o for o in outcomes}
        failed = by_name["failure"].context.devices["dev-1"]
        self.assertEqual(failed.errors[-1].code, "ambiguous_content")
        self.assertEqual(failed.errors[-1].failure.kind, "ambiguous_match")
        self.assertEqual(by_name["match"].context.devices, {})


if __name__ == "__main__":
    unittest.main()

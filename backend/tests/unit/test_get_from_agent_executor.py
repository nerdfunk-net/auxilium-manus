"""Tests for the get-from-agent executor and its request parsing."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from models.failure import failure_from_exception
from models.workflow_context import WorkflowContext
from services.agents.exceptions import (
    AgentAuthError,
    AgentHandlerError,
    AgentOfflineError,
    AgentTimeoutError,
)
from services.agents.source_config_service import AgentConnection
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.get_from_agent import executor as mod
from workflow_steps.get_from_agent.executor import execute
from workflow_steps.get_from_agent.request import build_inputs, parse_config

BASE_CONFIG: dict[str, Any] = {
    "agent_source_id": "inv",
    "handler": "list_devices",
    "attributes": [{"name": "site", "value": "berlin"}],
}
ANSWER = {
    "devices": [
        {"name": "r1", "ip_address": "10.0.0.1", "network_driver": "cisco_ios"},
        {"name": "r2"},
    ]
}


def _connection(**overrides: Any) -> AgentConnection:
    values: dict[str, Any] = {
        "source_id": "inv",
        "transport": "http",
        "agent_id": "agent-inv",
        "url": "http://agent:8080",
        "max_concurrency": 4,
        "max_request_bytes": 1_048_576,
        "max_timeout_seconds": 60,
        "secret": "s" * 40,
    }
    values.update(overrides)
    return AgentConnection(**values)


class FakeClient:
    def __init__(self, answer: Any = None, error: Exception | None = None) -> None:
        self.answer = ANSWER if answer is None else answer
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def invoke(self, handler, params, inputs, *, timeout=None):
        self.calls.append(
            {"handler": handler, "params": params, "inputs": inputs, "timeout": timeout}
        )
        if self.error:
            raise self.error
        return self.answer

    async def aclose(self) -> None:
        self.closed = True


async def _run(config: dict[str, Any], client: FakeClient, *, run_inputs=None, connection=None):
    run = SimpleNamespace(id=7, uuid="run-uuid", run_inputs=run_inputs or {})
    context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={})
    with (
        patch.object(mod, "object_session", return_value=MagicMock()),
        patch.object(mod, "resolve_agent_connection", return_value=connection or _connection()),
        patch.object(mod.service_factory, "build_agent_client", return_value=client),
    ):
        return await execute(
            config=config,
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )


class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_builds_devices_from_the_answer(self) -> None:
        client = FakeClient()
        outcomes = await _run(BASE_CONFIG, client)
        self.assertEqual([o.name for o in outcomes], ["success"])
        devices = list(outcomes[0].context.devices.values())
        self.assertEqual([d.name for d in devices], ["r1", "r2"])
        self.assertEqual(devices[0].primary_ip4, "10.0.0.1")
        self.assertEqual(devices[1].network_driver, "cisco_ios")
        self.assertEqual(devices[0].source, "agent")
        self.assertEqual(outcomes[0].context.metadata["n1.total"], 2)
        self.assertEqual(outcomes[0].context.metadata["n1.agent"], "inv")
        self.assertTrue(client.closed)

    async def test_blank_driver_from_an_agent_becomes_the_default(self) -> None:
        # The reachable-ip-inventory agent answers network_driver "" for every device.
        answer = {"devices": [{"name": "gw", "ip_address": "10.0.0.1", "network_driver": ""}]}
        outcomes = await _run(BASE_CONFIG, FakeClient(answer))
        device = next(iter(outcomes[0].context.devices.values()))
        self.assertEqual(device.network_driver, "cisco_ios")

    async def test_sends_attributes_and_no_params(self) -> None:
        client = FakeClient()
        await _run(BASE_CONFIG, client)
        call = client.calls[0]
        self.assertEqual(call["handler"], "list_devices")
        self.assertEqual(call["params"], {})
        self.assertEqual(call["inputs"], {"attributes": {"site": "berlin"}, "content": {}})
        self.assertEqual(call["timeout"], 30)

    async def test_fan_out_metadata_is_set_when_enabled(self) -> None:
        config = {**BASE_CONFIG, "fan_out": {"enabled": True, "mode": "per_device"}}
        outcomes = await _run(config, FakeClient())
        self.assertIn("_fan_out", outcomes[0].context.metadata)

    async def test_run_input_reference_is_resolved(self) -> None:
        config = {**BASE_CONFIG, "attributes": [{"name": "site", "value": "{run_input.site}"}]}
        client = FakeClient()
        await _run(config, client, run_inputs={"site": "paris"})
        self.assertEqual(client.calls[0]["inputs"]["attributes"], {"site": "paris"})

    async def test_missing_run_input_is_a_configuration_error(self) -> None:
        config = {**BASE_CONFIG, "attributes": [{"name": "site", "value": "{run_input.site}"}]}
        with self.assertRaisesRegex(ValueError, "not present"):
            await _run(config, FakeClient())

    async def test_sealed_run_input_is_refused(self) -> None:
        config = {**BASE_CONFIG, "attributes": [{"name": "site", "value": "{run_input.site}"}]}
        with (
            patch("services.workflow_context.secret_fields.EncryptionService") as enc,
        ):
            enc.return_value.encrypt.return_value = b"token"
            sealed = seal_secret("x")
        with self.assertRaisesRegex(ValueError, "secret"):
            await _run(config, FakeClient(), run_inputs={"site": sealed})

    async def test_agent_error_fails_the_step(self) -> None:
        client = FakeClient(error=AgentOfflineError("agent is offline"))
        with self.assertRaisesRegex(RuntimeError, "offline"):
            await _run(BASE_CONFIG, client)
        self.assertTrue(client.closed)

    async def test_handler_error_fails_the_step(self) -> None:
        client = FakeClient(error=AgentHandlerError("ValueError", "boom"))
        with self.assertRaisesRegex(RuntimeError, "boom"):
            await _run(BASE_CONFIG, client)

    async def test_the_step_failure_keeps_the_classification_of_the_agent_error(self) -> None:
        # W8-02: the record the step stores is read from the cause chain of what it raises.
        cases = [
            (AgentOfflineError("agent is offline"), "agent_offline", True),
            (AgentTimeoutError("no answer"), "timeout", True),
            (AgentAuthError("wrong secret"), "auth_failed", False),
            (AgentHandlerError("ValueError", "boom"), "agent_handler_error", False),
        ]
        for error, kind, retryable in cases:
            with self.subTest(kind=kind):
                with self.assertRaises(RuntimeError) as raised:
                    await _run(BASE_CONFIG, FakeClient(error=error))
                failure = failure_from_exception(raised.exception)
                assert failure is not None
                self.assertEqual((failure.phase, failure.kind), ("agent", kind))
                self.assertEqual(failure.retryable, retryable)
                self.assertEqual(failure.exception_type, type(error).__name__)

    async def test_empty_list_fails(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no devices"):
            await _run(BASE_CONFIG, FakeClient({"devices": []}))

    async def test_missing_devices_key_fails(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "'devices' list"):
            await _run(BASE_CONFIG, FakeClient({"devices": "r1"}))

    async def test_extra_keys_fail(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unexpected keys"):
            await _run(BASE_CONFIG, FakeClient({"devices": [{"name": "a"}], "x": 1}))

    async def test_invalid_row_fails_the_whole_step(self) -> None:
        answer = {"devices": [{"name": "a"}, {"name": "b", "ip_address": "not-an-ip"}]}
        with self.assertRaisesRegex(ValueError, "get-from-agent: invalid IP address"):
            await _run(BASE_CONFIG, FakeClient(answer))

    async def test_non_object_row_fails(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "object or a name"):
            await _run(BASE_CONFIG, FakeClient({"devices": [42]}))

    async def test_blank_row_fails_instead_of_being_dropped(self) -> None:
        for bad in ({}, {"name": "  ", "ip_address": ""}, {"network_driver": "x"}, "  "):
            answer = {"devices": [{"name": "ok", "ip_address": "10.0.0.1"}, bad]}
            with self.subTest(row=bad), self.assertRaisesRegex(RuntimeError, "neither a name"):
                await _run(BASE_CONFIG, FakeClient(answer))

    async def test_non_text_fields_fail(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "must be text"):
            await _run(BASE_CONFIG, FakeClient({"devices": [{"name": 5}]}))

    async def test_forbidden_hosts_fail(self) -> None:
        for row in (
            {"name": "x", "ip_address": "127.0.0.1"},
            {"ip_address": "169.254.169.254"},
            {"ip_address": "::1"},
            {"ip_address": "0.0.0.0"},  # noqa: S104
            {"ip_address": "224.0.0.1"},
            {"name": "metadata.google.internal"},
        ):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, "not allowed"):
                await _run(BASE_CONFIG, FakeClient({"devices": [row]}))

    async def test_non_plain_ip_fails(self) -> None:
        for ip in ("10.0.0.1/24", "10.0.0.01"):
            with self.subTest(ip=ip), self.assertRaisesRegex(ValueError, "plain IP"):
                await _run(BASE_CONFIG, FakeClient({"devices": [{"ip_address": ip}]}))

    async def test_persisted_name_list_is_capped(self) -> None:
        rows = [{"name": f"device-{i:04d}"} for i in range(mod.MAX_LISTED_NAMES + 20)]
        outcomes = await _run(BASE_CONFIG, FakeClient({"devices": rows}))
        metadata = outcomes[0].context.metadata
        self.assertEqual(len(metadata["n1.devices"]), mod.MAX_LISTED_NAMES)
        self.assertEqual(metadata["n1.total"], mod.MAX_LISTED_NAMES + 20)

    async def test_timeout_above_agent_maximum_is_refused(self) -> None:
        config = {**BASE_CONFIG, "timeout_seconds": 120}
        with self.assertRaisesRegex(ValueError, "maximum of 60"):
            await _run(config, FakeClient())


class ParseTests(unittest.TestCase):
    def test_blank_rows_are_ignored(self) -> None:
        parsed = parse_config({**BASE_CONFIG, "attributes": [{"name": "", "value": ""}]})
        self.assertEqual(parsed.attributes, ())

    def test_duplicate_names_are_refused(self) -> None:
        rows = [{"name": "a", "value": "1"}, {"name": "a", "value": "2"}]
        with self.assertRaisesRegex(ValueError, "unique"):
            parse_config({**BASE_CONFIG, "attributes": rows})

    def test_secret_looking_name_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "secret"):
            parse_config({**BASE_CONFIG, "attributes": [{"name": "api_token", "value": "x"}]})

    def test_bad_name_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "plain name"):
            parse_config({**BASE_CONFIG, "attributes": [{"name": "a.b", "value": "x"}]})

    def test_required_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "agent_source_id"):
            parse_config({**BASE_CONFIG, "agent_source_id": ""})
        with self.assertRaisesRegex(ValueError, "handler is required"):
            parse_config({**BASE_CONFIG, "handler": ""})
        with self.assertRaisesRegex(ValueError, "valid handler"):
            parse_config({**BASE_CONFIG, "handler": "1bad"})

    def test_attributes_may_be_absent(self) -> None:
        parsed = parse_config({"agent_source_id": "inv", "handler": "h"})
        self.assertEqual(build_inputs(parsed, None), {"attributes": {}, "content": {}})

    def test_unresolvable_run_input_reference_is_refused(self) -> None:
        for value in ("{run_input.site.region}", "{run_input.site code}", "x{run_input.site}"):
            parsed = parse_config({**BASE_CONFIG, "attributes": [{"name": "s", "value": value}]})
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "whole value"):
                build_inputs(parsed, {"site": "x"})

    def test_non_scalar_run_input_is_refused(self) -> None:
        parsed = parse_config(
            {**BASE_CONFIG, "attributes": [{"name": "s", "value": "{run_input.s}"}]}
        )
        with self.assertRaisesRegex(ValueError, "plain value"):
            build_inputs(parsed, {"s": {"a": 1}})


if __name__ == "__main__":
    unittest.main()

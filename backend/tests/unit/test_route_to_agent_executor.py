"""Tests for the route-to-agent executor."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    ArtifactRef,
    Capability,
    CommandResult,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.agents.exceptions import (
    AgentAuthError,
    AgentHandlerError,
    AgentOfflineError,
    AgentPayloadTooLargeError,
    AgentTimeoutError,
)
from services.agents.source_config_service import AgentConnection
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.route_to_agent import executor as mod
from workflow_steps.route_to_agent import output as output_mod
from workflow_steps.route_to_agent.config import get_config
from workflow_steps.route_to_agent.executor import execute

BASE_CONFIG: dict[str, Any] = {
    "agent_source_id": "geo",
    "handler": "resolve_location",
    "params": {"strict": True},
    "input_paths": ["nautobot.location.name"],
    "content_inputs": [],
    "destination_path": "agent.geo",
    "output_keys": ["location"],
}


def _connection(**overrides: Any) -> AgentConnection:
    values: dict[str, Any] = {
        "source_id": "geo",
        "transport": "http",
        "agent_id": "agent-geo",
        "url": "http://geo-agent:8080",
        "max_concurrency": 4,
        "max_request_bytes": 1_048_576,
        "max_timeout_seconds": 60,
        "secret": "s" * 40,
    }
    values.update(overrides)
    return AgentConnection(**values)


def _device(device_id: str, **kwargs: Any) -> DeviceContext:
    bags = kwargs.pop("attribute_bags", {"nautobot": {"location": {"name": f"site-{device_id}"}}})
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        attribute_bags=bags,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
        **kwargs,
    )


def _context(*devices: DeviceContext) -> WorkflowContext:
    return WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={d.id: d for d in devices})


class FakeClient:
    def __init__(self, behaviour=None):
        self.behaviour = behaviour or (lambda handler, params, inputs: {"location": "Berlin"})
        self.calls: list[dict[str, Any]] = []
        self.closed = False
        self.in_flight = 0
        self.max_in_flight = 0

    async def invoke(self, handler, params, inputs, *, timeout=None):
        self.calls.append(
            {"handler": handler, "params": params, "inputs": inputs, "timeout": timeout}
        )
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            result = self.behaviour(handler, params, inputs)
            if isinstance(result, Exception):
                raise result
            return result
        finally:
            self.in_flight -= 1

    async def aclose(self):
        self.closed = True


async def _run(
    config: dict[str, Any],
    context: WorkflowContext,
    *,
    client: FakeClient | None = None,
    connection: AgentConnection | None = None,
    artifact_service: Any = None,
):
    fake = client or FakeClient()
    with (
        patch.object(mod, "object_session", return_value=MagicMock()),
        patch.object(mod, "resolve_agent_connection", return_value=connection or _connection()),
        patch.object(mod.service_factory, "build_agent_client", return_value=fake),
    ):
        outcomes = await execute(
            config=config,
            context=context,
            run=MagicMock(),
            artifact_service=artifact_service or MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )
    return outcomes, fake


def _by_name(outcomes):
    return {o.name: o for o in outcomes}


class SuccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_output_lands_under_the_destination_bag(self) -> None:
        outcomes, fake = await _run(dict(BASE_CONFIG), _context(_device("d1"), _device("d2")))

        self.assertEqual([o.name for o in outcomes], ["success"])
        devices = outcomes[0].context.devices
        self.assertEqual(devices["d1"].attribute_bags["agent"]["geo"], {"location": "Berlin"})
        self.assertEqual(list(devices), ["d1", "d2"])
        self.assertIn(Capability.ATTRIBUTES, devices["d1"].capabilities)
        self.assertTrue(fake.closed)

    async def test_request_carries_handler_params_and_selected_inputs_only(self) -> None:
        device = _device(
            "d1",
            attribute_bags={
                "nautobot": {"location": {"name": "Hamburg"}, "role": "core"},
                "other": {"x": 1},
            },
        )
        _, fake = await _run(dict(BASE_CONFIG), _context(device))
        call = fake.calls[0]
        self.assertEqual(call["handler"], "resolve_location")
        self.assertEqual(call["params"], {"strict": True})
        self.assertEqual(
            call["inputs"], {"attributes": {"nautobot.location.name": "Hamburg"}, "content": {}}
        )

    async def test_structured_values_keep_their_shape(self) -> None:
        config = {**BASE_CONFIG, "input_paths": ["nautobot.location"]}
        _, fake = await _run(config, _context(_device("d1")))
        self.assertEqual(
            fake.calls[0]["inputs"]["attributes"], {"nautobot.location": {"name": "site-d1"}}
        )

    async def test_unresolved_paths_are_omitted(self) -> None:
        config = {**BASE_CONFIG, "input_paths": ["nautobot.location.name", "nautobot.nothing"]}
        _, fake = await _run(config, _context(_device("d1")))
        self.assertEqual(list(fake.calls[0]["inputs"]["attributes"]), ["nautobot.location.name"])

    async def test_destination_can_be_nested_and_leaves_the_rest_alone(self) -> None:
        device = _device("d1")
        config = {**BASE_CONFIG, "destination_path": "agent.geo.result"}
        outcomes, _ = await _run(config, _context(device))
        result = outcomes[0].context.devices["d1"]
        self.assertEqual(result.attribute_bags["agent"]["geo"]["result"], {"location": "Berlin"})
        self.assertEqual(result.attribute_bags["nautobot"], device.attribute_bags["nautobot"])
        self.assertEqual((result.name, result.hostname, result.id), ("d1", "d1", "d1"))

    async def test_content_inputs_are_read_from_artifacts(self) -> None:
        ref = ArtifactRef(artifact_id="a1", kind="running_config", media_type="text/plain")
        artifacts = MagicMock()
        artifacts.resolve = AsyncMock(return_value="hostname d1\n")
        config = {**BASE_CONFIG, "content_inputs": ["running_config", "startup_config"]}
        _, fake = await _run(
            config,
            _context(_device("d1", running_config_ref=ref)),
            artifact_service=artifacts,
        )
        # startup config is absent on this device -> omitted
        self.assertEqual(fake.calls[0]["inputs"]["content"], {"running_config": "hostname d1\n"})
        artifacts.resolve.assert_awaited_once_with(ref)

    async def test_empty_context_does_nothing(self) -> None:
        outcomes, fake = await _run({}, _context())
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertEqual(fake.calls, [])


class InputContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_sealed_secret_input_fails_the_device_without_calling_the_agent(self) -> None:
        sealed = _device(
            "d1", attribute_bags={"nautobot": {"location": {"name": seal_secret("hunter2hunter2")}}}
        )
        outcomes, fake = await _run(dict(BASE_CONFIG), _context(sealed, _device("d2")))
        by_name = _by_name(outcomes)
        self.assertEqual(list(by_name["failure"].context.devices), ["d1"])
        error = by_name["failure"].context.devices["d1"].errors[0]
        self.assertEqual(error.code, "source_sealed")
        self.assertEqual(error.failure.phase, "agent")  # type: ignore[union-attr]
        self.assertEqual([c["inputs"]["attributes"] for c in fake.calls],
                         [{"nautobot.location.name": "site-d2"}])
        self.assertNotIn("hunter2", repr(fake.calls))

    async def test_sealed_secret_nested_in_a_structure_is_also_refused(self) -> None:
        location = {"name": "x", "k": seal_secret("abcdefgh12")}
        nested = _device("d1", attribute_bags={"nautobot": {"location": location}})
        config = {**BASE_CONFIG, "input_paths": ["nautobot.location"]}
        outcomes, fake = await _run(config, _context(nested))
        self.assertIn("failure", _by_name(outcomes))
        self.assertEqual(fake.calls, [])


class SecretInputTests(unittest.IsolatedAsyncioTestCase):
    """Cleartext secrets must not leave the app either: the same rules store-for-report applies."""

    async def _config_error(self, *paths: str) -> None:
        for path in paths:
            with self.subTest(path=path), self.assertRaises(ValueError) as ctx:
                await _run({**BASE_CONFIG, "input_paths": [path]}, _context(_device("d1")))
            assert "secret" in str(ctx.exception).lower(), path

    async def test_known_secret_paths_are_refused(self) -> None:
        await self._config_error(
            "tacacs.shared_secret",
            "ise.tacacsSettings.sharedSecret",
            "pyats_testbed.password",
            "tacacs.shared_secret.extra",
        )

    async def test_config_context_documents_are_refused_whole_or_in_part(self) -> None:
        await self._config_error(
            "nautobot.config_context",
            "nautobot.config_context.tacacs.key",
            "nautobot.local_config_context_data",
            "nautobot.config_context[name=a].x",
        )

    async def test_a_parent_that_would_carry_a_secret_along_is_refused(self) -> None:
        # "nautobot" resolves to the whole bag, config_context included
        await self._config_error("nautobot", "tacacs", "ise", "ise.tacacsSettings")

    async def test_paths_with_a_secret_looking_segment_are_refused(self) -> None:
        await self._config_error(
            "nautobot.devices.password", "parsed.api.api_token", "x.y.enable_secret"
        )

    async def test_ordinary_paths_are_allowed(self) -> None:
        for path in (
            "nautobot.location.name",
            "nautobot.platform.network_driver",
            "ise.profile",
            "pyats_testbed.hostname",
            "device.hostname",
        ):
            with self.subTest(path=path):
                config = {**BASE_CONFIG, "input_paths": [path]}
                outcomes, _ = await _run(config, _context(_device("d1")))
                assert [o.name for o in outcomes] == ["success"]

    async def test_a_secret_named_key_inside_a_selected_structure_fails_the_device(self) -> None:
        creds = {"user": "noc", "password": "hunter2hunter2"}
        device = _device("d1", attribute_bags={"custom": {"creds": creds}})
        config = {**BASE_CONFIG, "input_paths": ["custom.creds"]}
        outcomes, fake = await _run(config, _context(device))
        error = _by_name(outcomes)["failure"].context.devices["d1"].errors[0]
        assert error.code == "source_secret"
        assert "hunter2" not in error.message and "hunter2" not in repr(fake.calls)
        assert fake.calls == []

    async def test_an_empty_secret_named_key_is_not_a_secret(self) -> None:
        creds = {"user": "noc", "password": ""}
        device = _device("d1", attribute_bags={"custom": {"creds": creds}})
        config = {**BASE_CONFIG, "input_paths": ["custom.creds"]}
        outcomes, _ = await _run(config, _context(device))
        assert [o.name for o in outcomes] == ["success"]

    async def test_secret_named_keys_inside_lists_are_found(self) -> None:
        hosts = [{"name": "a", "api_key": "k" * 20}]
        device = _device("d1", attribute_bags={"custom": {"hosts": hosts}})
        config = {**BASE_CONFIG, "input_paths": ["custom.hosts"]}
        outcomes, fake = await _run(config, _context(device))
        assert _by_name(outcomes)["failure"].context.devices["d1"].errors[0].code == "source_secret"
        assert fake.calls == []


class CommandOutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_command_result_is_sent_even_when_the_command_text_repeats(self) -> None:
        refs = [ArtifactRef(artifact_id=f"a{i}", kind="command_output") for i in range(3)]
        def result(command: str, ref: ArtifactRef) -> CommandResult:
            return CommandResult(node_id="run-1", command=command, success=True, output_ref=ref)

        results = [
            result("show version", refs[0]),
            result("show clock", refs[1]),
            result("show version", refs[2]),
        ]
        device = _device("d1", command_results={"run-1": results})
        texts = {"a0": "first", "a1": "clock", "a2": "second"}
        artifacts = MagicMock()
        artifacts.resolve = AsyncMock(side_effect=lambda ref: texts[ref.artifact_id])
        config = {**BASE_CONFIG, "content_inputs": ["command_output:run-1"]}
        _, fake = await _run(config, _context(device), artifact_service=artifacts)
        assert fake.calls[0]["inputs"]["content"]["command_output:run-1"] == [
            {"command": "show version", "output": "first"},
            {"command": "show clock", "output": "clock"},
            {"command": "show version", "output": "second"},
        ]

    async def test_a_step_without_results_leaves_the_content_out(self) -> None:
        config = {**BASE_CONFIG, "content_inputs": ["command_output:run-1"]}
        _, fake = await _run(config, _context(_device("d1")))
        assert fake.calls[0]["inputs"]["content"] == {}


class OutputContractTests(unittest.IsolatedAsyncioTestCase):
    async def _fail_code(self, behaviour, config=None) -> tuple[str, Any]:
        outcomes, _ = await _run(
            config or dict(BASE_CONFIG), _context(_device("d1")), client=FakeClient(behaviour)
        )
        by_name = _by_name(outcomes)
        self.assertEqual(by_name["success"].context.devices, {})
        error = by_name["failure"].context.devices["d1"].errors[0]
        return error.code, error.failure

    async def test_undeclared_key_is_rejected(self) -> None:
        code, failure = await self._fail_code(lambda *_: {"location": "x", "extra": 1})
        self.assertEqual((code, failure.kind), ("output_rejected", "output_rejected"))

    async def test_missing_declared_key_is_rejected_unless_allowed(self) -> None:
        code, _ = await self._fail_code(lambda *_: {})
        self.assertEqual(code, "output_rejected")
        config = {**BASE_CONFIG, "allow_missing_outputs": True}
        outcomes, _ = await _run(config, _context(_device("d1")), client=FakeClient(lambda *_: {}))
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertEqual(outcomes[0].context.devices["d1"].attribute_bags["agent"]["geo"], {})

    async def test_key_names_that_would_break_dot_paths_are_rejected(self) -> None:
        config = {**BASE_CONFIG, "output_keys": ["a"]}
        code, _ = await self._fail_code(lambda *_: {"a.b": 1}, config)
        self.assertEqual(code, "output_rejected")

    async def test_oversized_value_is_rejected(self) -> None:
        with patch.object(output_mod.settings, "step_output_value_max_bytes", 1024):
            code, _ = await self._fail_code(lambda *_: {"location": "x" * 5000})
        self.assertEqual(code, "output_rejected")

    async def test_absurdly_deep_value_is_rejected_not_an_internal_error(self) -> None:
        deep: Any = "leaf"
        for _ in range(20_000):  # far beyond the interpreter's recursion limit
            deep = {"n": deep}
        code, failure = await self._fail_code(lambda *_: {"location": deep})
        assert (code, failure.kind) == ("output_rejected", "output_rejected")

    async def test_too_deep_value_is_rejected(self) -> None:
        deep: Any = "leaf"
        for _ in range(20):
            deep = {"n": deep}
        code, _ = await self._fail_code(lambda *_: {"location": deep})
        self.assertEqual(code, "output_rejected")

    async def test_json_structures_are_accepted(self) -> None:
        value = {"name": "Berlin", "tags": ["a", "b"], "floor": 3, "ok": True, "none": None}
        client = FakeClient(lambda *_: {"location": value})
        outcomes, _ = await _run(dict(BASE_CONFIG), _context(_device("d1")), client=client)
        bag = outcomes[0].context.devices["d1"].attribute_bags["agent"]["geo"]
        self.assertEqual(bag["location"], value)


class FailureMappingTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_errors_become_structured_device_failures(self) -> None:
        cases = [
            (AgentTimeoutError("slow"), "agent_timeout", "timeout", True),
            (AgentAuthError("bad secret"), "agent_auth_failed", "auth_failed", False),
            (
                AgentHandlerError("KeyError", "boom"),
                "agent_handler_error",
                "agent_handler_error",
                False,
            ),
            (AgentPayloadTooLargeError("big"), "payload_too_large", "payload_too_large", False),
        ]
        for exc, code, kind, retryable in cases:
            with self.subTest(kind=kind):
                outcomes, _ = await _run(
                    dict(BASE_CONFIG),
                    _context(_device("d1")),
                    client=FakeClient(lambda *_a, e=exc: e),
                )
                error = _by_name(outcomes)["failure"].context.devices["d1"].errors[0]
                self.assertEqual(error.code, code)
                self.assertEqual(error.step_id, "route-to-agent")
                self.assertEqual(error.failure.phase, "agent")  # type: ignore[union-attr]
                self.assertEqual(error.failure.kind, kind)  # type: ignore[union-attr]
                self.assertEqual(error.failure.retryable, retryable)  # type: ignore[union-attr]
                self.assertEqual(
                    _by_name(outcomes)["failure"].context.devices["d1"].status, DeviceStatus.FAILED
                )

    async def test_unexpected_exception_is_reduced_to_its_class_name(self) -> None:
        outcomes, _ = await _run(
            dict(BASE_CONFIG),
            _context(_device("d1")),
            client=FakeClient(lambda *_: RuntimeError("password=hunter2 leaked")),
        )
        error = _by_name(outcomes)["failure"].context.devices["d1"].errors[0]
        self.assertNotIn("hunter2", error.message)
        self.assertEqual(error.failure.kind, "internal_error")  # type: ignore[union-attr]

    async def test_mixed_results_split_between_outcomes(self) -> None:
        def behaviour(handler, params, inputs):
            if inputs["attributes"]["nautobot.location.name"] == "site-d2":
                return AgentHandlerError("ValueError", "bad site")
            return {"location": "ok"}

        outcomes, _ = await _run(
            dict(BASE_CONFIG),
            _context(_device("d1"), _device("d2"), _device("d3")),
            client=FakeClient(behaviour),
        )
        by_name = _by_name(outcomes)
        self.assertEqual(list(by_name["success"].context.devices), ["d1", "d3"])
        self.assertEqual(list(by_name["failure"].context.devices), ["d2"])
        self.assertNotIn("agent", by_name["failure"].context.devices["d2"].attribute_bags)

    async def test_offline_agent_fails_the_remaining_devices_without_more_calls(self) -> None:
        client = FakeClient(lambda *_: AgentOfflineError("down"))
        devices = [_device(f"d{i}") for i in range(6)]
        outcomes, _ = await _run(
            dict(BASE_CONFIG),
            _context(*devices),
            client=client,
            connection=_connection(max_concurrency=1),
        )
        by_name = _by_name(outcomes)
        self.assertEqual(by_name["success"].context.devices, {})
        self.assertEqual(len(by_name["failure"].context.devices), 6)
        self.assertEqual(len(client.calls), 1)
        for device in by_name["failure"].context.devices.values():
            self.assertEqual(device.errors[0].failure.kind, "agent_offline")  # type: ignore[union-attr]

    async def test_client_is_closed_even_when_calls_fail(self) -> None:
        _, client = await _run(
            dict(BASE_CONFIG),
            _context(_device("d1")),
            client=FakeClient(lambda *_: AgentTimeoutError("slow")),
        )
        self.assertTrue(client.closed)


class ConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_in_flight_calls_are_capped_by_the_agent_limit(self) -> None:
        client = FakeClient()
        devices = [_device(f"d{i}") for i in range(10)]
        outcomes, _ = await _run(
            dict(BASE_CONFIG), _context(*devices), client=client,
            connection=_connection(max_concurrency=2),
        )
        self.assertEqual(len(outcomes[0].context.devices), 10)
        self.assertEqual(client.max_in_flight, 2)

    async def test_a_step_timeout_above_the_agents_maximum_is_a_config_error(self) -> None:
        # Used to be capped silently, so a step set to 120 s failed at 60 s as "agent_timeout".
        with self.assertRaises(ValueError) as ctx:
            await _run(
                {**BASE_CONFIG, "timeout_seconds": 120},
                _context(_device("d1")),
                connection=_connection(max_timeout_seconds=60),
            )
        assert "60" in str(ctx.exception) and "timeout" in str(ctx.exception)

    async def test_a_step_timeout_equal_to_the_maximum_is_fine(self) -> None:
        _, client = await _run(
            {**BASE_CONFIG, "timeout_seconds": 60},
            _context(_device("d1")),
            connection=_connection(max_timeout_seconds=60),
        )
        assert client.calls[0]["timeout"] == 60

    async def test_timeout_setting_is_passed_to_the_client(self) -> None:
        _, client = await _run({**BASE_CONFIG, "timeout_seconds": 7}, _context(_device("d1")))
        self.assertEqual(client.calls[0]["timeout"], 7)


class ConfigValidationTests(unittest.IsolatedAsyncioTestCase):
    async def _expect_error(self, **overrides: Any) -> None:
        config = {**BASE_CONFIG, **overrides}
        with self.assertRaises(ValueError):
            await _run(config, _context(_device("d1")))

    async def test_required_fields(self) -> None:
        for field in ("agent_source_id", "handler", "destination_path", "output_keys"):
            with self.subTest(field=field):
                await self._expect_error(**{field: "" if field != "output_keys" else []})

    async def test_destination_path_rules(self) -> None:
        for bad in ("device.name", "parsed.agent", "run_input.agent", "agent", "name", "a b.c"):
            with self.subTest(path=bad):
                await self._expect_error(destination_path=bad)

    async def test_output_keys_must_be_plain_names(self) -> None:
        for bad in (["a.b"], ["has space"], [""], ["a", "a"], "location"):
            with self.subTest(keys=bad):
                await self._expect_error(output_keys=bad)

    async def test_needs_at_least_one_input(self) -> None:
        await self._expect_error(input_paths=[], content_inputs=[])

    async def test_unknown_content_input(self) -> None:
        await self._expect_error(content_inputs=["etc_passwd"])

    async def test_params_must_be_a_json_object(self) -> None:
        for bad in ("text", [1], {"x": object()}):
            with self.subTest(params=bad):
                await self._expect_error(params=bad)

    async def test_timeout_bounds(self) -> None:
        for bad in (0, -1, 601, "soon"):
            with self.subTest(timeout=bad):
                await self._expect_error(timeout_seconds=bad)

    async def test_unknown_source_is_a_config_error(self) -> None:
        with (
            patch.object(mod, "object_session", return_value=MagicMock()),
            patch.object(mod, "resolve_agent_connection", side_effect=ValueError("no such source")),
            self.assertRaises(ValueError),
        ):
            await execute(
                config=dict(BASE_CONFIG),
                context=_context(_device("d1")),
                run=MagicMock(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    def test_default_config_has_every_field(self) -> None:
        self.assertEqual(
            set(get_config()),
            {
                "agent_source_id", "handler", "params", "input_paths", "content_inputs",
                "destination_path", "output_keys", "allow_missing_outputs", "timeout_seconds",
            },
        )


if __name__ == "__main__":
    unittest.main()

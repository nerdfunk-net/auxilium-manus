"""Tests for the secret-get executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.secret_manager.exceptions import SecretManagerUnavailableError
from services.workflow_context.secret_fields import is_sealed_secret, unwrap_secret
from workflow_steps.secret_get import executor as mod
from workflow_steps.secret_get.executor import execute

BASE_CONFIG = {
    "connection_id": 1,
    "path_template": "network/{device.name}/tacacs",
    "field": "key",
    "destination_path": "tacacs.shared_secret",
}


def _device(device_id: str) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


def _named(name: str, device_id: str) -> DeviceContext:
    return _device(device_id).model_copy(update={"name": name})


def _context(devices: dict[str, DeviceContext]) -> WorkflowContext:
    return WorkflowContext(run_id="run-1", workflow_id="wf-1", devices=devices)


async def _run(config: dict, context: WorkflowContext, *, get_field):
    service = MagicMock()
    service.get_field = get_field
    with (
        patch.object(mod, "object_session", return_value=MagicMock()),
        patch.object(mod, "SecretManagerService", return_value=service),
    ):
        return await execute(
            config=config,
            context=context,
            run=MagicMock(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )


class SecretGetExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_connection_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            await _run(
                {**BASE_CONFIG, "connection_id": None},
                _context({}),
                get_field=AsyncMock(),
            )

    async def test_version_string_is_coerced(self) -> None:
        get_field = AsyncMock(return_value="s3cr3t")
        await _run(
            {**BASE_CONFIG, "version": "3"}, _context({"d1": _device("d1")}), get_field=get_field
        )
        self.assertEqual(get_field.call_args.kwargs["version"], 3)

    async def test_version_garbage_raises(self) -> None:
        for bad in ("abc", True, 1.5, float("inf"), []):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                await _run(
                    {**BASE_CONFIG, "version": bad},
                    _context({"d1": _device("d1")}),
                    get_field=AsyncMock(),
                )

    async def test_version_zero_raises(self) -> None:
        with self.assertRaises(ValueError):
            await _run(
                {**BASE_CONFIG, "version": 0},
                _context({"d1": _device("d1")}),
                get_field=AsyncMock(),
            )

    async def test_invalid_field_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            await _run(
                {**BASE_CONFIG, "field": "../x"},
                _context({"d1": _device("d1")}),
                get_field=AsyncMock(),
            )

    async def test_missing_optional_keys_fall_back_to_config_py_defaults(self) -> None:
        # Regression: a canvas node whose config was never actually edited (only
        # displayed with an illustrative default in the UI) sends a config dict
        # with path_template/field/destination_path genuinely absent, not just
        # empty. Must behave identically to explicitly-set defaults, not raise.
        minimal_config = {"connection_id": 1}
        context = _context({"d1": _device("d1")})
        outcomes = await _run(minimal_config, context, get_field=AsyncMock(return_value="s3cr3t"))

        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["d1"]
        sealed = device.attribute_bags["tacacs"]["shared_secret"]
        self.assertEqual(unwrap_secret(sealed), "s3cr3t")

    async def test_found_value_is_sealed_into_destination(self) -> None:
        context = _context({"d1": _device("d1")})
        outcomes = await _run(BASE_CONFIG, context, get_field=AsyncMock(return_value="s3cr3t"))

        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["d1"]
        sealed = device.attribute_bags["tacacs"]["shared_secret"]
        self.assertTrue(is_sealed_secret(sealed))
        self.assertEqual(unwrap_secret(sealed), "s3cr3t")
        self.assertEqual(outcomes[0].context.metadata["node-1.found_count"], 1)

    async def test_missing_value_routes_device_to_failure_but_step_succeeds(self) -> None:
        context = _context({"d1": _device("d1")})
        outcomes = await _run(BASE_CONFIG, context, get_field=AsyncMock(return_value=None))

        names = [o.name for o in outcomes]
        self.assertEqual(names, ["success", "failure"])
        failed = outcomes[1].context.devices["d1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(outcomes[0].context.devices, {})

    async def test_vault_lost_midway_reports_written_devices(self) -> None:
        context = _context({d: _device(d) for d in ("d1", "d2", "d3")})
        outcomes = await _run(
            BASE_CONFIG,
            context,
            get_field=AsyncMock(side_effect=["v", SecretManagerUnavailableError("down"), 1]),
        )
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["success"].context.devices), ["d1"])
        self.assertEqual(sorted(by_name["failure"].context.devices), ["d2", "d3"])
        self.assertEqual(by_name["success"].context.metadata["node-1.processed"], ["d1"])
        error = by_name["failure"].context.devices["d2"].errors[-1]
        self.assertEqual(error.code, "remote_system_lost")
        self.assertEqual(error.failure.kind, "server_error")

    async def test_unsafe_name_is_mapped_to_a_valid_path(self) -> None:
        names = ["Büro-sw (alt)", "sw#1", "sw,01"]
        context = _context({f"d{i}": _named(name, f"d{i}") for i, name in enumerate(names)})
        call = AsyncMock(return_value="v")
        outcomes = await _run(BASE_CONFIG, context, get_field=call)
        self.assertEqual([o.name for o in outcomes], ["success"])
        paths = [c.args[1] for c in call.await_args_list]
        self.assertEqual(
            paths,
            ["network/B_ro-sw _alt_/tacacs", "network/sw_1/tacacs", "network/sw_01/tacacs"],
        )

    async def test_colliding_paths_fail_the_second_device(self) -> None:
        context = _context({"d1": _named("a:b", "d1"), "d2": _named("a_b", "d2")})
        call = AsyncMock(return_value="v")
        outcomes = await _run(BASE_CONFIG, context, get_field=call)
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["success"].context.devices), ["d1"])
        self.assertEqual(list(by_name["failure"].context.devices), ["d2"])
        self.assertEqual(by_name["failure"].context.devices["d2"].errors[-1].code, "duplicate_key")
        self.assertEqual(call.await_count, 1)


if __name__ == "__main__":
    unittest.main()

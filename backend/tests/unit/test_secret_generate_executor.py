"""Tests for the secret-generate executor.

The key property under test: the raw generated value must never appear in
plaintext in the step's metadata or logs — only as a sealed envelope in the
device's attribute bag (see doc/SECRET_MANAGER_INTEGRATION.md's "pipe-only"
decision).
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.secret_manager.exceptions import SecretManagerUnavailableError
from services.workflow_context.secret_fields import is_sealed_secret, unwrap_secret
from workflow_steps.secret_generate import executor as mod
from workflow_steps.secret_generate.executor import execute

BASE_CONFIG = {
    "connection_id": 1,
    "path_template": "network/{device.name}/tacacs",
    "field": "key",
    "destination_path": "tacacs.shared_secret",
    "charset": "hex",
    "length": 32,
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


async def _run(config: dict, context: WorkflowContext, *, generate_field):
    service = MagicMock()
    service.generate_field = generate_field
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


class SecretGenerateExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_unsupported_charset(self) -> None:
        with self.assertRaises(ValueError):
            await _run(
                {**BASE_CONFIG, "charset": "not-a-charset"},
                _context({}),
                generate_field=AsyncMock(),
            )

    async def test_rejects_out_of_range_length(self) -> None:
        with self.assertRaises(ValueError):
            await _run(
                {**BASE_CONFIG, "length": 1},
                _context({}),
                generate_field=AsyncMock(),
            )

    async def test_missing_optional_keys_fall_back_to_config_py_defaults(self) -> None:
        # Regression: a canvas node whose config was never actually edited (only
        # displayed with an illustrative default in the UI) sends a config dict
        # with path_template/field/destination_path genuinely absent, not just
        # empty. Must behave identically to explicitly-set defaults, not raise.
        minimal_config = {"connection_id": 1}
        context = _context({"d1": _device("d1")})
        outcomes = await _run(
            minimal_config, context, generate_field=AsyncMock(return_value=(1, "deadbeef"))
        )

        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["d1"]
        sealed = device.attribute_bags["tacacs"]["shared_secret"]
        self.assertEqual(unwrap_secret(sealed), "deadbeef")

    async def test_generated_value_is_sealed_never_plaintext_in_metadata(self) -> None:
        context = _context({"d1": _device("d1")})
        outcomes = await _run(
            BASE_CONFIG, context, generate_field=AsyncMock(return_value=(3, "deadbeef"))
        )

        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["d1"]
        sealed = device.attribute_bags["tacacs"]["shared_secret"]
        self.assertTrue(is_sealed_secret(sealed))
        self.assertEqual(unwrap_secret(sealed), "deadbeef")

        # The raw value must not leak into metadata (which is what persists
        # to WorkflowStepResult) under any key, serialized or not.
        metadata_blob = json.dumps(outcomes[0].context.metadata)
        self.assertNotIn("deadbeef", metadata_blob)
        self.assertEqual(outcomes[0].context.metadata["node-1.generated_count"], 1)

    async def test_vault_lost_midway_reports_written_devices(self) -> None:
        context = _context({d: _device(d) for d in ("d1", "d2", "d3")})
        outcomes = await _run(
            BASE_CONFIG,
            context,
            generate_field=AsyncMock(
                side_effect=[(1, "v"), SecretManagerUnavailableError("down"), 1]
            ),
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
        call = AsyncMock(return_value=(1, "v"))
        outcomes = await _run(BASE_CONFIG, context, generate_field=call)
        self.assertEqual([o.name for o in outcomes], ["success"])
        paths = [c.args[1] for c in call.await_args_list]
        self.assertEqual(
            paths,
            ["network/B_ro-sw _alt_/tacacs", "network/sw_1/tacacs", "network/sw_01/tacacs"],
        )

    async def test_colliding_paths_fail_the_second_device(self) -> None:
        context = _context({"d1": _named("a:b", "d1"), "d2": _named("a_b", "d2")})
        call = AsyncMock(return_value=(1, "v"))
        outcomes = await _run(BASE_CONFIG, context, generate_field=call)
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["success"].context.devices), ["d1"])
        self.assertEqual(list(by_name["failure"].context.devices), ["d2"])
        self.assertEqual(by_name["failure"].context.devices["d2"].errors[-1].code, "duplicate_key")
        self.assertEqual(call.await_count, 1)


if __name__ == "__main__":
    unittest.main()

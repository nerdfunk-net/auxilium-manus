"""Tests for the secret-set executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.secret_manager.exceptions import SecretManagerUnavailableError
from services.workflow_context.secret_fields import is_sealed_secret, seal_secret, unwrap_secret
from workflow_steps.secret_set import executor as mod
from workflow_steps.secret_set.executor import execute

BASE_CONFIG = {
    "connection_id": 1,
    "path_template": "network/{device.name}/tacacs",
    "field": "key",
    "source_path": "run_input.new_tacacs_key",
    "destination_path": "tacacs.shared_secret",
}


def _device(device_id: str, *, attribute_bags: dict | None = None) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        attribute_bags=attribute_bags or {},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


def _device_with_run_input(device_id: str, value: str) -> DeviceContext:
    return _device(device_id, attribute_bags={"run_input": {"new_tacacs_key": value}})


def _context(devices: dict[str, DeviceContext]) -> WorkflowContext:
    return WorkflowContext(run_id="run-1", workflow_id="wf-1", devices=devices)


async def _run(config: dict, context: WorkflowContext, *, set_field):
    service = MagicMock()
    service.set_field = set_field
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


class SecretSetExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_fixed_mode_is_rejected_with_hint(self) -> None:
        # SM3: a workflow saved before the literal mode was removed must fail
        # loudly, naming the migration path -- never silently write nothing.
        with self.assertRaisesRegex(ValueError, "run_input"):
            await _run(
                {**BASE_CONFIG, "mode": "fixed", "fixed_value": "new-key"},
                _context({"d1": _device("d1")}),
                set_field=AsyncMock(),
            )

    async def test_fixed_value_alone_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "no longer supported"):
            await _run(
                {**BASE_CONFIG, "fixed_value": "new-key"},
                _context({"d1": _device("d1")}),
                set_field=AsyncMock(),
            )

    async def test_blank_source_path_falls_back_to_default(self) -> None:
        context = _context({"d1": _device_with_run_input("d1", "new-key")})
        outcomes = await _run(
            {**BASE_CONFIG, "source_path": ""}, context, set_field=AsyncMock(return_value=1)
        )
        self.assertEqual([o.name for o in outcomes], ["success"])

    async def test_missing_optional_keys_fall_back_to_config_py_defaults(self) -> None:
        # Regression: a canvas node whose config was never actually edited (only
        # displayed with an illustrative default in the UI) sends a config dict
        # with path_template/field/source_path/destination_path genuinely
        # absent, not just empty. Must behave identically to explicitly-set
        # defaults, not raise.
        minimal_config = {"connection_id": 1}
        context = _context({"d1": _device_with_run_input("d1", "new-key")})
        outcomes = await _run(minimal_config, context, set_field=AsyncMock(return_value=1))

        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["d1"]
        sealed = device.attribute_bags["tacacs"]["shared_secret"]
        self.assertEqual(unwrap_secret(sealed), "new-key")

    async def test_run_input_value_is_written_and_sealed(self) -> None:
        context = _context({"d1": _device_with_run_input("d1", "new-key")})
        set_field = AsyncMock(return_value=2)
        outcomes = await _run(BASE_CONFIG, context, set_field=set_field)

        set_field.assert_awaited_once_with(1, "network/d1/tacacs", "key", "new-key")
        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["d1"]
        sealed = device.attribute_bags["tacacs"]["shared_secret"]
        self.assertTrue(is_sealed_secret(sealed))
        self.assertEqual(unwrap_secret(sealed), "new-key")
        self.assertEqual(outcomes[0].context.metadata["node-1.written_count"], 1)
        # The plaintext never lands in metadata (unchanged invariant).
        self.assertNotIn("new-key", str(outcomes[0].context.metadata))

    async def test_attribute_mode_reads_sealed_source_value(self) -> None:
        context = _context(
            {
                "d1": _device(
                    "d1", attribute_bags={"run_input": {"new_key": seal_secret("run-supplied")}}
                )
            }
        )
        cfg = {**BASE_CONFIG, "source_path": "run_input.new_key"}
        set_field = AsyncMock(return_value=1)
        outcomes = await _run(cfg, context, set_field=set_field)

        self.assertEqual([o.name for o in outcomes], ["success"])
        set_field.assert_awaited_once_with(1, "network/d1/tacacs", "key", "run-supplied")

    async def test_unresolved_source_routes_device_to_failure(self) -> None:
        context = _context({"d1": _device("d1")})
        cfg = {**BASE_CONFIG, "source_path": "run_input.missing"}
        outcomes = await _run(cfg, context, set_field=AsyncMock())

        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        failed = outcomes[1].context.devices["d1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)

    async def test_connection_error_fails_whole_step(self) -> None:
        context = _context({"d1": _device_with_run_input("d1", "new-key")})
        outcomes = await _run(
            BASE_CONFIG,
            context,
            set_field=AsyncMock(side_effect=SecretManagerUnavailableError("down")),
        )
        self.assertEqual([o.name for o in outcomes], ["failure"])


if __name__ == "__main__":
    unittest.main()

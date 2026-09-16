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

    async def test_missing_optional_keys_fall_back_to_config_py_defaults(self) -> None:
        # Regression: a canvas node whose config was never actually edited (only
        # displayed with an illustrative default in the UI) sends a config dict
        # with path_template/field/destination_path genuinely absent, not just
        # empty. Must behave identically to explicitly-set defaults, not raise.
        minimal_config = {"connection_id": 1}
        context = _context({"d1": _device("d1")})
        outcomes = await _run(
            minimal_config, context, get_field=AsyncMock(return_value="s3cr3t")
        )

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

    async def test_connection_error_fails_whole_step(self) -> None:
        context = _context({"d1": _device("d1"), "d2": _device("d2")})
        outcomes = await _run(
            BASE_CONFIG,
            context,
            get_field=AsyncMock(side_effect=SecretManagerUnavailableError("down")),
        )

        self.assertEqual([o.name for o in outcomes], ["failure"])


if __name__ == "__main__":
    unittest.main()

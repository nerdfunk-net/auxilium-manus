"""Tests for the encrypt-attribute executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core.passphrase_cipher import decrypt_with_passphrase
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.encrypt_attribute import executor as mod
from workflow_steps.encrypt_attribute.executor import execute

_PASSPHRASE = "shared-secret-passphrase"


def _device(device_id: str, *, attribute_bags: dict | None = None) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        attribute_bags=attribute_bags or {},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


def _context(devices: dict[str, DeviceContext]) -> WorkflowContext:
    return WorkflowContext(run_id="run-1", workflow_id="wf-1", devices=devices)


BASE_CONFIG = {
    "source_path": "run_input.enable_password",
    "destination_path": "secrets.enable_password_enc",
    "credential_reference": "vault",
}


async def _run(config: dict, context: WorkflowContext):
    with (
        patch.object(mod, "object_session", return_value=MagicMock()),
        patch.object(
            mod,
            "resolve_shared_secret_credential",
            return_value=("aes-256-gcm", _PASSPHRASE),
        ),
    ):
        return await execute(
            config=config,
            context=context,
            run=MagicMock(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )


class EncryptAttributeExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_encrypts_source_into_destination(self) -> None:
        context = _context(
            {"d1": _device("d1", attribute_bags={"run_input": {"enable_password": "cisco123"}})}
        )
        outcomes = await _run(dict(BASE_CONFIG), context)

        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["d1"]
        token = device.attribute_bags["secrets"]["enable_password_enc"]
        self.assertTrue(token.startswith("AM1.aes-256-gcm."))
        self.assertEqual(decrypt_with_passphrase(token, _PASSPHRASE), "cisco123")
        self.assertIn(Capability.ATTRIBUTES, device.capabilities)
        self.assertEqual(outcomes[0].context.metadata["node-1.encrypted_count"], 1)

    async def test_missing_source_skips_device(self) -> None:
        context = _context({"d1": _device("d1")})
        outcomes = await _run(dict(BASE_CONFIG), context)

        device = outcomes[0].context.devices["d1"]
        self.assertNotIn("secrets", device.attribute_bags)
        self.assertEqual(outcomes[0].context.metadata["node-1.skipped_count"], 1)

    async def test_sealed_source_routes_to_failure(self) -> None:
        context = _context(
            {"d1": _device("d1", attribute_bags={"tacacs": {"shared_secret": seal_secret("x")}})}
        )
        cfg = {**BASE_CONFIG, "source_path": "tacacs.shared_secret"}
        outcomes = await _run(cfg, context)

        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        failed = outcomes[1].context.devices["d1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[-1].code, "source_sealed")
        self.assertEqual(failed.errors[-1].step_id, "encrypt-attribute")

    async def test_missing_config_raises_value_error(self) -> None:
        context = _context({"d1": _device("d1")})
        bad = {"source_path": "", "destination_path": "x", "credential_reference": "v"}
        with self.assertRaises(ValueError):
            await _run(bad, context)

    async def test_no_devices_returns_success(self) -> None:
        outcomes = await _run(dict(BASE_CONFIG), _context({}))
        self.assertEqual([o.name for o in outcomes], ["success"])


if __name__ == "__main__":
    unittest.main()

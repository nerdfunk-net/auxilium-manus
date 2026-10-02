"""Tests for the encrypt-attribute executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from network_secret import cisco_type7

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

    async def test_missing_credential_raises_for_aes(self) -> None:
        context = _context({"d1": _device("d1")})
        bad = {"source_path": "a.b", "destination_path": "x.y"}
        with self.assertRaises(ValueError):
            await _run(bad, context)


class EncryptAttributeCiscoTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _config(algorithm: str) -> dict:
        return {
            "source_path": "run_input.pw",
            "destination_path": "secrets.pw_enc",
            "algorithm": algorithm,
        }

    @staticmethod
    def _ctx(value: str) -> WorkflowContext:
        return _context({"d1": _device("d1", attribute_bags={"run_input": {"pw": value}})})

    async def _run_keyless(self, config: dict, context: WorkflowContext):
        with (
            patch.object(mod, "object_session", return_value=None),
            patch.object(mod, "resolve_shared_secret_credential") as resolver,
        ):
            outcomes = await execute(
                config=config,
                context=context,
                run=MagicMock(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )
        resolver.assert_not_called()
        return outcomes

    async def test_type7_needs_no_credential_or_db(self) -> None:
        outcomes = await self._run_keyless(self._config("cisco-type7"), self._ctx("tacacs-key"))

        device = outcomes[0].context.devices["d1"]
        token = device.attribute_bags["secrets"]["pw_enc"]
        self.assertEqual(cisco_type7.decrypt(token), "tacacs-key")
        self.assertEqual(outcomes[0].context.metadata["node-1.algorithm"], "cisco-type7")

    async def test_type8_and_type9_hash(self) -> None:
        for algo, prefix in (("cisco-type8", "$8$"), ("cisco-type9", "$9$")):
            outcomes = await self._run_keyless(self._config(algo), self._ctx("S3cret"))
            value = outcomes[0].context.devices["d1"].attribute_bags["secrets"]["pw_enc"]
            self.assertTrue(value.startswith(prefix))

    async def test_type7_unencodable_value_routes_to_failure(self) -> None:
        outcomes = await self._run_keyless(self._config("cisco-type7"), self._ctx("pw✓"))

        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        failed = outcomes[1].context.devices["d1"]
        self.assertEqual(failed.errors[-1].code, "encryption_failed")
        self.assertNotIn("pw✓", failed.errors[-1].message)

    async def test_unknown_algorithm_is_config_error(self) -> None:
        with self.assertRaises(ValueError):
            await self._run_keyless(self._config("cisco-type5"), self._ctx("x"))


if __name__ == "__main__":
    unittest.main()

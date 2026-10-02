"""Tests for the decrypt-attribute executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from network_secret import cisco_type7

from core.passphrase_cipher import encrypt_with_passphrase
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.workflow_context.secret_fields import is_sealed_secret, unwrap_secret
from workflow_steps.decrypt_attribute import executor as mod
from workflow_steps.decrypt_attribute.executor import execute

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
    "source_path": "nautobot.config_context.enable_password",
    "destination_path": "secrets.enable_password",
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


class DecryptAttributeExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_decrypts_into_sealed_destination(self) -> None:
        token = encrypt_with_passphrase("cisco123", _PASSPHRASE)
        context = _context(
            {
                "d1": _device(
                    "d1",
                    attribute_bags={"nautobot": {"config_context": {"enable_password": token}}},
                )
            }
        )
        outcomes = await _run(dict(BASE_CONFIG), context)

        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["d1"]
        stored = device.attribute_bags["secrets"]["enable_password"]
        self.assertTrue(is_sealed_secret(stored))
        self.assertEqual(unwrap_secret(stored), "cisco123")
        self.assertIn(Capability.ATTRIBUTES, device.capabilities)
        self.assertEqual(outcomes[0].context.metadata["node-1.decrypted_count"], 1)

    async def test_missing_source_skips_device(self) -> None:
        context = _context({"d1": _device("d1")})
        outcomes = await _run(dict(BASE_CONFIG), context)

        device = outcomes[0].context.devices["d1"]
        self.assertNotIn("secrets", device.attribute_bags)
        self.assertEqual(outcomes[0].context.metadata["node-1.skipped_count"], 1)

    async def test_wrong_secret_routes_to_failure_without_stopping_run(self) -> None:
        token = encrypt_with_passphrase("cisco123", "a-different-secret")
        context = _context(
            {
                "d1": _device(
                    "d1",
                    attribute_bags={"nautobot": {"config_context": {"enable_password": token}}},
                )
            }
        )
        outcomes = await _run(dict(BASE_CONFIG), context)

        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        self.assertEqual(dict(outcomes[0].context.devices), {})
        failed = outcomes[1].context.devices["d1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[-1].code, "decryption_failed")
        self.assertEqual(failed.errors[-1].step_id, "decrypt-attribute")
        self.assertEqual(failed.errors[-1].node_id, "node-1")
        self.assertNotIn("secrets", failed.attribute_bags)
        self.assertEqual(outcomes[0].context.metadata["node-1.failed_count"], 1)

    async def test_partial_failure_routes_only_the_bad_device(self) -> None:
        good = encrypt_with_passphrase("good-pw", _PASSPHRASE)
        bad = encrypt_with_passphrase("bad-pw", "some-other-secret")
        context = _context(
            {
                "ok": _device(
                    "ok",
                    attribute_bags={"nautobot": {"config_context": {"enable_password": good}}},
                ),
                "bad": _device(
                    "bad",
                    attribute_bags={"nautobot": {"config_context": {"enable_password": bad}}},
                ),
            }
        )
        outcomes = await _run(dict(BASE_CONFIG), context)

        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        self.assertEqual(set(outcomes[0].context.devices), {"ok"})
        self.assertEqual(set(outcomes[1].context.devices), {"bad"})
        self.assertEqual(
            unwrap_secret(outcomes[0].context.devices["ok"].attribute_bags["secrets"]["enable_password"]),
            "good-pw",
        )

    async def test_round_trip_with_encrypt_executor(self) -> None:
        from workflow_steps.encrypt_attribute import executor as enc_mod
        from workflow_steps.encrypt_attribute.executor import execute as encrypt

        context = _context(
            {"d1": _device("d1", attribute_bags={"run_input": {"pw": "topsecret"}})}
        )
        with (
            patch.object(enc_mod, "object_session", return_value=MagicMock()),
            patch.object(
                enc_mod,
                "resolve_shared_secret_credential",
                return_value=("aes-256-gcm", _PASSPHRASE),
            ),
        ):
            enc_outcomes = await encrypt(
                config={
                    "source_path": "run_input.pw",
                    "destination_path": "vault.pw_enc",
                    "credential_reference": "vault",
                },
                context=context,
                run=MagicMock(),
                artifact_service=MagicMock(),
                node_id="enc",
                device_sessions=MagicMock(),
            )

        dec_outcomes = await _run(
            {
                "source_path": "vault.pw_enc",
                "destination_path": "secrets.pw",
                "credential_reference": "vault",
            },
            enc_outcomes[0].context,
        )
        stored = dec_outcomes[0].context.devices["d1"].attribute_bags["secrets"]["pw"]
        self.assertEqual(unwrap_secret(stored), "topsecret")

    async def test_missing_config_raises_value_error(self) -> None:
        context = _context({"d1": _device("d1")})
        bad = {"source_path": "a.b", "destination_path": "", "credential_reference": "v"}
        with self.assertRaises(ValueError):
            await _run(bad, context)


_LIST_CONFIG = {
    "source_path": "nautobot.config_context.credentials",
    "credential_reference": "vault",
    "item_field": "password",
}


def _creds_device(device_id: str, credentials: list) -> DeviceContext:
    return _device(
        device_id,
        attribute_bags={"nautobot": {"config_context": {"credentials": credentials}}},
    )


class DecryptAttributeListModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_decrypts_item_field_on_every_entry_sealed_in_place(self) -> None:
        device = _creds_device(
            "d1",
            [
                {"username": "admin", "privilege": 15,
                 "password": encrypt_with_passphrase("adminpw", _PASSPHRASE)},
                {"username": "noc", "privilege": 15,
                 "password": encrypt_with_passphrase("nocpw", _PASSPHRASE)},
                {"username": "readonly", "privilege": 1},  # no password field
            ],
        )
        outcomes = await _run(dict(_LIST_CONFIG), _context({"d1": device}))

        self.assertEqual([o.name for o in outcomes], ["success"])
        creds = outcomes[0].context.devices["d1"].attribute_bags["nautobot"][
            "config_context"
        ]["credentials"]
        self.assertTrue(is_sealed_secret(creds[0]["password"]))
        self.assertEqual(unwrap_secret(creds[0]["password"]), "adminpw")
        self.assertEqual(unwrap_secret(creds[1]["password"]), "nocpw")
        self.assertEqual(creds[0]["username"], "admin")  # other fields untouched
        self.assertNotIn("password", creds[2])
        self.assertEqual(outcomes[0].context.metadata["node-1.mode"], "list")

    async def test_input_device_is_not_mutated(self) -> None:
        device = _creds_device(
            "d1",
            [{"username": "noc", "password": encrypt_with_passphrase("nocpw", _PASSPHRASE)}],
        )
        await _run(dict(_LIST_CONFIG), _context({"d1": device}))
        original = device.attribute_bags["nautobot"]["config_context"]["credentials"][0]
        self.assertFalse(is_sealed_secret(original["password"]))

    async def test_one_bad_token_routes_device_to_failure_and_writes_nothing(self) -> None:
        device = _creds_device(
            "d1",
            [
                {"username": "admin",
                 "password": encrypt_with_passphrase("adminpw", _PASSPHRASE)},
                {"username": "noc",
                 "password": encrypt_with_passphrase("nocpw", "the-wrong-secret")},
            ],
        )
        outcomes = await _run(dict(_LIST_CONFIG), _context({"d1": device}))

        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        failed = outcomes[1].context.devices["d1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[-1].code, "decryption_failed")
        self.assertIn("noc", failed.errors[-1].message)
        # atomic: nothing sealed on the failed device
        creds = failed.attribute_bags["nautobot"]["config_context"]["credentials"]
        self.assertFalse(is_sealed_secret(creds[0]["password"]))

    async def test_source_not_a_list_routes_to_failure(self) -> None:
        device = _device(
            "d1",
            attribute_bags={"nautobot": {"config_context": {"credentials": {"not": "a list"}}}},
        )
        outcomes = await _run(dict(_LIST_CONFIG), _context({"d1": device}))
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        self.assertEqual(
            outcomes[1].context.devices["d1"].errors[-1].code, "not_a_list"
        )

    async def test_no_decryptable_entries_is_skipped(self) -> None:
        device = _creds_device("d1", [{"username": "noc", "privilege": 1}])
        outcomes = await _run(dict(_LIST_CONFIG), _context({"d1": device}))
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertEqual(outcomes[0].context.metadata["node-1.skipped_count"], 1)

    async def test_writes_to_explicit_destination_path(self) -> None:
        device = _creds_device(
            "d1",
            [{"username": "noc", "password": encrypt_with_passphrase("nocpw", _PASSPHRASE)}],
        )
        cfg = {**_LIST_CONFIG, "destination_path": "deploy.credentials"}
        outcomes = await _run(cfg, _context({"d1": device}))

        bags = outcomes[0].context.devices["d1"].attribute_bags
        self.assertEqual(unwrap_secret(bags["deploy"]["credentials"][0]["password"]), "nocpw")
        # source list left as raw tokens
        src = bags["nautobot"]["config_context"]["credentials"][0]["password"]
        self.assertFalse(is_sealed_secret(src))

    async def test_partial_failure_across_devices(self) -> None:
        good = _creds_device(
            "good",
            [{"username": "noc", "password": encrypt_with_passphrase("nocpw", _PASSPHRASE)}],
        )
        bad = _creds_device(
            "bad",
            [{"username": "noc", "password": encrypt_with_passphrase("x", "other")}],
        )
        outcomes = await _run(dict(_LIST_CONFIG), _context({"good": good, "bad": bad}))
        self.assertEqual(set(outcomes[0].context.devices), {"good"})
        self.assertEqual(set(outcomes[1].context.devices), {"bad"})


def _cc(config_context: dict) -> dict:
    return {"nautobot": {"config_context": config_context}}


class DecryptAttributeCiscoTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_type7_scalar_decrypts_sealed_without_credential(self) -> None:
        token = cisco_type7.encrypt("tacacs-key")
        context = _context(
            {"d1": _device("d1", attribute_bags=_cc({"enable_password": token}))}
        )
        cfg = {**BASE_CONFIG, "algorithm": "cisco-type7"}
        cfg.pop("credential_reference")
        outcomes = await self._run_keyless(cfg, context)

        value = outcomes[0].context.devices["d1"].attribute_bags["secrets"]["enable_password"]
        self.assertTrue(is_sealed_secret(value))
        self.assertEqual(unwrap_secret(value), "tacacs-key")
        self.assertEqual(outcomes[0].context.metadata["node-1.algorithm"], "cisco-type7")

    async def test_type7_list_mode(self) -> None:
        creds = [{"username": "a", "password": cisco_type7.encrypt("pw-a")}]
        context = _context(
            {"d1": _device("d1", attribute_bags=_cc({"credentials": creds}))}
        )
        cfg = {
            "source_path": "nautobot.config_context.credentials",
            "item_field": "password",
            "algorithm": "cisco-type7",
        }
        outcomes = await self._run_keyless(cfg, context)

        bags = outcomes[0].context.devices["d1"].attribute_bags
        out = bags["nautobot"]["config_context"]["credentials"]
        self.assertEqual(unwrap_secret(out[0]["password"]), "pw-a")

    async def test_malformed_type7_routes_device_to_failure(self) -> None:
        context = _context(
            {"d1": _device("d1", attribute_bags=_cc({"enable_password": "zz"}))}
        )
        cfg = {**BASE_CONFIG, "algorithm": "cisco-type7"}
        outcomes = await self._run_keyless(cfg, context)

        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        self.assertEqual(outcomes[1].context.devices["d1"].errors[-1].code, "decryption_failed")

    async def test_one_way_types_are_config_errors(self) -> None:
        context = _context({"d1": _device("d1")})
        for algo in ("cisco-type8", "cisco-type9"):
            with self.assertRaises(ValueError) as ctx:
                await self._run_keyless({**BASE_CONFIG, "algorithm": algo}, context)
            self.assertIn("one-way", str(ctx.exception))

    async def test_aes_still_requires_credential(self) -> None:
        context = _context({"d1": _device("d1")})
        cfg = {"source_path": "a.b", "destination_path": "x.y"}
        with self.assertRaises(ValueError):
            await self._run_keyless(cfg, context)


if __name__ == "__main__":
    unittest.main()

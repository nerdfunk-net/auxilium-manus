"""OpenBaoSecretManagerClient: construction policy, strict ensure_started,
field merge semantics, error mapping. OpenBaoService is mocked -- its own
wire behaviour is covered by test_vault_client.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from services.secret_manager.config import SecretManagerConnectionConfig
from services.secret_manager.exceptions import (
    SecretManagerAuthError,
    SecretManagerConfigError,
    SecretManagerUnavailableError,
)
from services.vault.exceptions import VaultSecretNotFoundError, VaultUnavailableError


def _cfg(**overrides) -> SecretManagerConnectionConfig:
    base = dict(
        id=1,
        name="net",
        backend="openbao",
        verify_ssl=True,
        backend_config={"addr": "https://vault.internal:8200", "mount": "manus-network"},
        auth_id="role-id",
        auth_secret="secret-id",
    )
    return SecretManagerConnectionConfig(**{**base, **overrides})


class OpenBaoSecretManagerClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        env = patch("services.secret_manager.transport_policy.settings.environment", "development")
        env.start()
        self.addCleanup(env.stop)
        svc_patcher = patch("services.secret_manager.openbao_client.OpenBaoService")
        self.svc_cls = svc_patcher.start()
        self.addCleanup(svc_patcher.stop)
        self.svc = self.svc_cls.return_value
        self.svc.startup = AsyncMock()
        self.svc.shutdown = AsyncMock()
        from services.secret_manager.openbao_client import OpenBaoSecretManagerClient

        self.cls = OpenBaoSecretManagerClient

    # ---- construction -------------------------------------------------------
    def test_missing_auth_material_is_config_error(self) -> None:
        with self.assertRaises(SecretManagerConfigError):
            self.cls(_cfg(auth_secret=""))

    def test_verify_ssl_false_outside_development_is_config_error(self) -> None:
        with patch("services.secret_manager.transport_policy.settings.environment", "production"):
            with self.assertRaisesRegex(SecretManagerConfigError, "verify_ssl=false"):
                self.cls(_cfg(verify_ssl=False))

    def test_http_addr_outside_development_is_config_error(self) -> None:
        with patch("services.secret_manager.transport_policy.settings.environment", "production"):
            with self.assertRaisesRegex(SecretManagerConfigError, "must use https"):
                self.cls(_cfg(backend_config={"addr": "http://vault:8200", "mount": "m"}))

    # ---- ensure_started (SM1) -----------------------------------------------
    async def test_ensure_started_raises_when_login_failed(self) -> None:
        type(self.svc).healthy = property(lambda _self: False)
        client = self.cls(_cfg())
        with self.assertRaisesRegex(SecretManagerAuthError, "AppRole login failed"):
            await client.ensure_started()
        self.svc.shutdown.assert_awaited_once()

    async def test_ensure_started_ok_when_healthy(self) -> None:
        type(self.svc).healthy = property(lambda _self: True)
        client = self.cls(_cfg())
        await client.ensure_started()
        self.svc.shutdown.assert_not_awaited()

    # ---- field semantics ----------------------------------------------------
    def test_get_field_missing_path_returns_none(self) -> None:
        self.svc.read_kv.side_effect = VaultSecretNotFoundError("nope")
        self.assertIsNone(self.cls(_cfg()).get_field("network/r1/tacacs", "key"))

    def test_get_field_pinned_version_bypasses_cache(self) -> None:
        self.svc.read_kv.return_value = {"key": "old"}
        self.assertEqual(self.cls(_cfg()).get_field("p", "key", version=2), "old")
        self.svc.read_kv.assert_called_once_with("p", version=2)

    def test_set_field_merges_existing_fields(self) -> None:
        self.svc.read_kv.return_value = {"key": "old", "rotated_at": "t0"}
        self.svc.write_kv.return_value = 3
        version = self.cls(_cfg()).set_field("p", "key", "new")
        self.svc.write_kv.assert_called_once_with("p", {"key": "new", "rotated_at": "t0"})
        self.assertEqual(version, 3)

    def test_delete_last_field_deletes_path(self) -> None:
        self.svc.read_kv.return_value = {"key": "v"}
        self.cls(_cfg()).delete_field("p", "key")
        self.svc.delete_kv.assert_called_once_with("p")
        self.svc.write_kv.assert_not_called()

    def test_vault_unavailable_maps_to_unavailable(self) -> None:
        self.svc.read_kv.side_effect = VaultUnavailableError("down")
        with self.assertRaises(SecretManagerUnavailableError):
            self.cls(_cfg()).get_field("p", "key")

    def test_history_skips_destroyed_and_sorts_desc(self) -> None:
        self.svc.metadata_kv.return_value = {
            "versions": {"1": {"created_time": "a"}, "2": {"created_time": "b", "destroyed": True},
                         "3": {"created_time": "c"}}
        }
        history = self.cls(_cfg()).get_field_history("p", "key")
        self.assertEqual([h.version for h in history], [3, 1])


if __name__ == "__main__":
    unittest.main()

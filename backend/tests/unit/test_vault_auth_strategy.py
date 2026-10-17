"""Auth-strategy selection, AppRole login, and token lifecycle."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from services.vault import auth as auth_mod
from services.vault.auth import (
    AppRoleAuth,
    CertAuth,
    TokenAuth,
    VaultToken,
    build_auth_strategy,
)
from services.vault.config import VaultConfig
from services.vault.exceptions import VaultAuthError, VaultConfigError
from services.vault.token_manager import VaultTokenManager


def _resp(status_code: int, body: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body or {}
    return response


def _cfg(**overrides) -> VaultConfig:
    base = {"addr": "https://vault.test:8200", "auth_method": "approle"}
    base.update(overrides)
    return VaultConfig(**base)


class BuildAuthStrategyTests(unittest.TestCase):
    def test_approle(self) -> None:
        self.assertIsInstance(build_auth_strategy(_cfg(auth_method="approle")), AppRoleAuth)

    def test_cert(self) -> None:
        self.assertIsInstance(build_auth_strategy(_cfg(auth_method="cert")), CertAuth)

    def test_token_allowed_in_development(self) -> None:
        # conftest leaves ENV unset -> "development"
        self.assertIsInstance(
            build_auth_strategy(_cfg(auth_method="token", token="root")), TokenAuth
        )

    def test_token_rejected_outside_development(self) -> None:
        original = auth_mod.settings.environment
        auth_mod.settings.environment = "production"
        try:
            with self.assertRaises(VaultConfigError):
                build_auth_strategy(_cfg(auth_method="token", token="root"))
        finally:
            auth_mod.settings.environment = original

    def test_unknown_method(self) -> None:
        with self.assertRaises(VaultConfigError):
            build_auth_strategy(_cfg(auth_method="ldap"))


class AppRoleAuthTests(unittest.TestCase):
    def test_login_posts_role_and_secret_id(self) -> None:
        http = MagicMock()
        http.post.return_value = _resp(
            200,
            {"auth": {"client_token": "s.abc", "lease_duration": 3600, "renewable": True}},
        )
        strategy = AppRoleAuth(_cfg(role_id="role-1", secret_id="secret-1"))

        token = strategy.login(http)

        http.post.assert_called_once_with(
            "/v1/auth/approle/login",
            json={"role_id": "role-1", "secret_id": "secret-1"},
        )
        self.assertEqual(token.client_token, "s.abc")
        self.assertTrue(token.renewable)

    def test_login_reads_secret_id_from_file(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".sid", delete=False) as handle:
            handle.write("  file-secret\n")
            path = handle.name

        http = MagicMock()
        http.post.return_value = _resp(200, {"auth": {"client_token": "s.xyz"}})
        strategy = AppRoleAuth(_cfg(role_id="role-1", secret_id_file=path))

        strategy.login(http)

        _, kwargs = http.post.call_args
        self.assertEqual(kwargs["json"]["secret_id"], "file-secret")

    def test_login_without_ids_raises(self) -> None:
        with self.assertRaises(VaultConfigError):
            AppRoleAuth(_cfg()).login(MagicMock())

    def test_login_non_200_raises(self) -> None:
        http = MagicMock()
        http.post.return_value = _resp(403)
        with self.assertRaises(VaultAuthError):
            AppRoleAuth(_cfg(role_id="r", secret_id="s")).login(http)


class VaultTokenManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = _cfg(role_id="r", secret_id="s")
        self.strategy = MagicMock()
        self.strategy.login.return_value = VaultToken(client_token="s.first", renewable=True)
        self.mgr = VaultTokenManager(self.cfg, self.strategy)

    def test_ensure_token_logs_in_once(self) -> None:
        http = MagicMock()
        self.mgr.ensure_token(http)
        self.mgr.ensure_token(http)
        self.assertEqual(self.strategy.login.call_count, 1)
        self.assertEqual(self.mgr.current(), "s.first")

    def test_invalidate_forces_relogin(self) -> None:
        http = MagicMock()
        self.mgr.ensure_token(http)
        self.mgr.invalidate()
        self.strategy.login.return_value = VaultToken(client_token="s.second", renewable=True)
        self.mgr.ensure_token(http)
        self.assertEqual(self.mgr.current(), "s.second")

    def test_renew_calls_renew_self(self) -> None:
        http = MagicMock()
        self.mgr.ensure_token(http)
        http.post.return_value = _resp(
            200, {"auth": {"client_token": "s.first", "renewable": True}}
        )
        self.mgr.renew(http)
        http.post.assert_called_once()
        self.assertEqual(http.post.call_args[0][0], "/v1/auth/token/renew-self")

    def test_renew_falls_back_to_login_on_403(self) -> None:
        http = MagicMock()
        self.mgr.ensure_token(http)
        http.post.return_value = _resp(403)
        self.strategy.login.return_value = VaultToken(client_token="s.relogin", renewable=True)
        self.mgr.renew(http)
        self.assertEqual(self.mgr.current(), "s.relogin")

    def test_current_without_token_raises(self) -> None:
        with self.assertRaises(VaultAuthError):
            self.mgr.current()

    def test_renew_interval_defaults_to_configured_without_token(self) -> None:
        self.assertEqual(self.mgr.renew_interval_seconds(), 3000)

    def test_renew_interval_follows_shorter_lease(self) -> None:
        http = MagicMock()
        self.strategy.login.return_value = VaultToken(
            client_token="s.first", renewable=True, lease_duration=900
        )
        self.mgr.ensure_token(http)
        self.assertEqual(self.mgr.renew_interval_seconds(), 300)

    def test_renew_interval_never_below_minimum(self) -> None:
        http = MagicMock()
        self.strategy.login.return_value = VaultToken(
            client_token="s.first", renewable=True, lease_duration=100
        )
        self.mgr.ensure_token(http)
        self.assertEqual(self.mgr.renew_interval_seconds(), 50)

        self.mgr.invalidate()
        self.strategy.login.return_value = VaultToken(
            client_token="s.second", renewable=True, lease_duration=40
        )
        self.mgr.ensure_token(http)
        self.assertEqual(self.mgr.renew_interval_seconds(), 30)

    def test_renew_interval_ignores_zero_lease_static_token(self) -> None:
        http = MagicMock()
        self.strategy.login.return_value = VaultToken(
            client_token="s.first", renewable=False, lease_duration=0
        )
        self.mgr.ensure_token(http)
        self.assertEqual(self.mgr.renew_interval_seconds(), 3000)

    def test_renew_relogins_for_non_renewable_leased_token(self) -> None:
        http = MagicMock()
        self.strategy.login.return_value = VaultToken(
            client_token="s.first", renewable=False, lease_duration=3600
        )
        self.mgr.ensure_token(http)
        self.strategy.login.return_value = VaultToken(
            client_token="s.second", renewable=False, lease_duration=3600
        )
        self.mgr.renew(http)
        self.assertEqual(self.strategy.login.call_count, 2)
        http.post.assert_not_called()
        self.assertEqual(self.mgr.current(), "s.second")

    def test_renew_skips_static_token(self) -> None:
        http = MagicMock()
        self.strategy.login.return_value = VaultToken(
            client_token="s.first", renewable=False, lease_duration=0
        )
        self.mgr.ensure_token(http)
        self.mgr.renew(http)
        self.assertEqual(self.strategy.login.call_count, 1)
        http.post.assert_not_called()

    def test_warn_if_lease_mismatch_logs_for_short_lease(self) -> None:
        http = MagicMock()
        self.strategy.login.return_value = VaultToken(
            client_token="s.first", renewable=True, lease_duration=900
        )
        self.mgr.ensure_token(http)
        with self.assertLogs("services.vault.token_manager", level="WARNING") as logs:
            self.mgr.warn_if_lease_mismatch()
        self.assertTrue(any("shorter than" in message for message in logs.output))

    def test_warn_if_lease_mismatch_logs_for_non_renewable(self) -> None:
        http = MagicMock()
        self.strategy.login.return_value = VaultToken(
            client_token="s.first", renewable=False, lease_duration=3600
        )
        self.mgr.ensure_token(http)
        with self.assertLogs("services.vault.token_manager", level="WARNING") as logs:
            self.mgr.warn_if_lease_mismatch()
        self.assertTrue(any("not renewable" in message for message in logs.output))

    def test_warn_if_lease_mismatch_silent_for_token_auth(self) -> None:
        http = MagicMock()
        cfg = _cfg(auth_method="token", token="root")
        mgr = VaultTokenManager(cfg, self.strategy)
        self.strategy.login.return_value = VaultToken(
            client_token="s.first", renewable=False, lease_duration=0
        )
        mgr.ensure_token(http)
        with self.assertNoLogs("services.vault.token_manager", level="WARNING"):
            mgr.warn_if_lease_mismatch()


if __name__ == "__main__":
    unittest.main()

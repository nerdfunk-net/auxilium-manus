"""Structural validation + production guards for the OpenBao settings."""

from __future__ import annotations

import unittest

from core.production_guards import validate_non_development_secrets

_STRONG_SECRET = "x" * 40
_STRONG_DB_PASSWORD = "a-strong-db-password"
_STRONG_INITIAL_PASSWORD = "a-strong-initial-pw"
_STRONG_REDIS_PASSWORD = "a-strong-redis-pw"


def _guard(**overrides) -> None:
    kwargs = {
        "environment": "production",
        "secret_key": _STRONG_SECRET,
        "initial_password": _STRONG_INITIAL_PASSWORD,
        "credential_encryption_key": _STRONG_SECRET + "-cek",
        "database_password": _STRONG_DB_PASSWORD,
        "enable_dev_tools": False,
        "redis_password": _STRONG_REDIS_PASSWORD,
        "allow_netmiko_arbitrary_hosts": False,
        # vault defaults: disabled
    }
    kwargs.update(overrides)
    validate_non_development_secrets(**kwargs)


class VaultProductionGuardTests(unittest.TestCase):
    def test_vault_disabled_passes(self) -> None:
        _guard()  # no raise

    def test_development_skips_all_vault_checks(self) -> None:
        _guard(environment="development", vault_enabled=True, vault_addr="http://x:8200")

    def test_http_addr_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "https"):
            _guard(
                vault_enabled=True,
                vault_addr="http://vault.internal:8200",
                vault_auth_method="approle",
                vault_role_id="r",
                vault_secret_id="s",
                vault_manage_role_id="mr",
                vault_manage_secret_id="ms",
            )

    def test_token_auth_rejected_outside_dev(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "token is only allowed in development"):
            _guard(
                vault_enabled=True,
                vault_addr="https://vault.internal:8200",
                vault_auth_method="token",
            )

    def test_approle_requires_role_and_secret_id(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "VAULT_ROLE_ID"):
            _guard(
                vault_enabled=True,
                vault_addr="https://vault.internal:8200",
                vault_auth_method="approle",
            )

    def test_approle_requires_management_role(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "VAULT_MANAGE_ROLE_ID"):
            _guard(
                vault_enabled=True,
                vault_addr="https://vault.internal:8200",
                vault_auth_method="approle",
                vault_role_id="r",
                vault_secret_id="s",
            )

    def test_secret_id_file_satisfies_requirement(self) -> None:
        _guard(
            vault_enabled=True,
            vault_addr="https://vault.internal:8200",
            vault_auth_method="approle",
            vault_role_id="r",
            vault_secret_id_file="/run/secrets/manus_secret_id",
            vault_manage_role_id="mr",
            vault_manage_secret_id_file="/run/secrets/manus_manage_secret_id",
        )

    def test_cert_auth_requires_client_cert_and_key(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "VAULT_CLIENT_CERT"):
            _guard(
                vault_enabled=True,
                vault_addr="https://vault.internal:8200",
                vault_auth_method="cert",
            )

    def test_cert_auth_ok_with_cert_and_key(self) -> None:
        _guard(
            vault_enabled=True,
            vault_addr="https://vault.internal:8200",
            vault_auth_method="cert",
            vault_client_cert="/etc/manus/vault.crt",
            vault_client_key="/etc/manus/vault.key",
        )

    def test_verify_ssl_false_rejected_outside_dev(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "VAULT_VERIFY_SSL"):
            _guard(
                vault_enabled=True,
                vault_addr="https://vault.internal:8200",
                vault_verify_ssl=False,
                vault_auth_method="approle",
                vault_role_id="r",
                vault_secret_id="s",
                vault_manage_role_id="mr",
                vault_manage_secret_id="ms",
            )

    def test_verify_ssl_false_allowed_in_development(self) -> None:
        _guard(
            environment="development",
            vault_enabled=True,
            vault_addr="https://vault.internal:8200",
            vault_verify_ssl=False,
        )


if __name__ == "__main__":
    unittest.main()

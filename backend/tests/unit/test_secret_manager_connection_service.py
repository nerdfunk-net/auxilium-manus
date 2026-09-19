"""CRUD tests for services/secret_manager/connection_service.py against
in-memory SQLite."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import SecretManagerConnection
from services.secret_manager.connection_service import SecretManagerConnectionService

_OPENBAO_BASE = {
    "name": "network-secrets",
    "backend": "openbao",
    "backend_config": {"addr": "https://vault.internal:8200", "mount": "manus-network"},
}

_INFISICAL_BASE = {
    "name": "network-secrets-infisical",
    "backend": "infisical",
    "backend_config": {
        "site_url": "https://app.infisical.com",
        "project_id": "proj-1",
        "environment": "prod",
    },
}


class SecretManagerConnectionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        SecretManagerConnection.metadata.create_all(
            engine, tables=[SecretManagerConnection.__table__]
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.service = SecretManagerConnectionService(self.db)

        # No real DNS in unit tests: keep the URL as-is unless it is one of
        # the cases the transport-policy tests below exercise explicitly.
        validate_patcher = patch(
            "services.secret_manager.transport_policy.validate_outbound_http_url",
            side_effect=lambda url, *, resolve_dns=True: url.rstrip("/"),
        )
        self.mock_validate = validate_patcher.start()
        self.addCleanup(validate_patcher.stop)
        env_patcher = patch(
            "services.secret_manager.transport_policy.settings.environment", "development"
        )
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

    def _create(self, **overrides) -> int:
        return self.service.create_connection({**_OPENBAO_BASE, **overrides})

    def test_create_applies_defaults(self) -> None:
        connection_id = self._create()
        stored = self.service.get_connection(connection_id)
        self.assertTrue(stored["verify_ssl"])
        self.assertTrue(stored["is_active"])
        self.assertEqual(stored["backend"], "openbao")

    def test_create_infisical_connection(self) -> None:
        connection_id = self.service.create_connection(dict(_INFISICAL_BASE))
        stored = self.service.get_connection(connection_id)
        self.assertEqual(stored["backend"], "infisical")
        self.assertEqual(stored["backend_config"]["project_id"], "proj-1")

    def test_create_rejects_duplicate_name(self) -> None:
        self._create()
        with self.assertRaises(ValueError):
            self._create()

    def test_create_rejects_unknown_backend(self) -> None:
        with self.assertRaises(ValueError):
            self._create(name="bogus", backend="hashicorp-vault-enterprise")

    def test_create_rejects_missing_openbao_config_fields(self) -> None:
        with self.assertRaises(ValueError):
            self._create(name="missing-mount", backend_config={"addr": "https://vault.internal"})

    def test_create_rejects_missing_infisical_config_fields(self) -> None:
        with self.assertRaises(ValueError):
            self.service.create_connection(
                {
                    "name": "bad-infisical",
                    "backend": "infisical",
                    "backend_config": {"site_url": "https://app.infisical.com"},
                }
            )

    def test_get_connection_missing_returns_none(self) -> None:
        self.assertIsNone(self.service.get_connection(999))

    def test_get_connections_filters_active(self) -> None:
        self._create(name="a")
        self._create(name="b", is_active=False)

        self.assertEqual(len(self.service.get_connections()), 2)
        self.assertEqual(len(self.service.get_connections(active_only=True)), 1)

    def test_update_connection_changes_fields(self) -> None:
        connection_id = self._create()
        self.assertTrue(self.service.update_connection(connection_id, {"is_active": False}))
        self.assertFalse(self.service.get_connection(connection_id)["is_active"])

    def test_update_connection_revalidates_backend_config(self) -> None:
        connection_id = self._create()
        with self.assertRaises(ValueError):
            self.service.update_connection(connection_id, {"backend_config": {"addr": "x"}})

    def test_update_connection_ignores_unknown_fields(self) -> None:
        connection_id = self._create()
        self.assertFalse(self.service.update_connection(connection_id, {"bogus": "x"}))

    def test_delete_connection(self) -> None:
        connection_id = self._create()
        self.assertTrue(self.service.delete_connection(connection_id))
        self.assertIsNone(self.service.get_connection(connection_id))

    # ---- SM2: transport policy -------------------------------------------
    def test_create_rejects_unsafe_url(self) -> None:
        from core.safe_urls import UnsafeURLError

        self.mock_validate.side_effect = UnsafeURLError("URL resolves to link-local address")
        with self.assertRaisesRegex(ValueError, "backend_config.addr"):
            self._create(backend_config={"addr": "http://169.254.169.254", "mount": "m"})

    def test_create_outside_development_requires_https(self) -> None:
        with patch(
            "services.secret_manager.transport_policy.settings.environment", "production"
        ):
            with self.assertRaisesRegex(ValueError, "must use https"):
                self._create(backend_config={"addr": "http://vault.internal:8200", "mount": "m"})

    def test_create_outside_development_requires_verify_ssl(self) -> None:
        with patch(
            "services.secret_manager.transport_policy.settings.environment", "production"
        ):
            with self.assertRaisesRegex(ValueError, "verify_ssl=false"):
                self._create(verify_ssl=False)

    def test_create_in_development_allows_http_and_no_verify(self) -> None:
        connection_id = self._create(
            verify_ssl=False,
            backend_config={"addr": "http://127.0.0.1:8200", "mount": "m"},
        )
        self.assertTrue(self.service.get_connection(connection_id)["backend_config"]["addr"])

    def test_update_verify_ssl_alone_is_policy_checked(self) -> None:
        connection_id = self._create()
        with patch(
            "services.secret_manager.transport_policy.settings.environment", "production"
        ):
            with self.assertRaisesRegex(ValueError, "verify_ssl=false"):
                self.service.update_connection(connection_id, {"verify_ssl": False})

    def test_infisical_site_url_is_policy_checked(self) -> None:
        from core.safe_urls import UnsafeURLError

        self.mock_validate.side_effect = UnsafeURLError("URL host is not allowed")
        with self.assertRaisesRegex(ValueError, "backend_config.site_url"):
            self.service.create_connection(
                {**_INFISICAL_BASE, "backend_config": {**_INFISICAL_BASE["backend_config"],
                                                       "site_url": "http://metadata.google.internal"}}
            )


if __name__ == "__main__":
    unittest.main()

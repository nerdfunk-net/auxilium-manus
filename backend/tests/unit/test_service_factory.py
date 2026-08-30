"""Tests for service_factory.py — construction + app-scoped singleton accessors."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import service_factory
from services.nautobot.credentials import NautobotCredentials

_SINGLETONS = (
    "_cache_service",
    "_nautobot_service",
    "_ise_service",
    "_pyats_service",
    "_mattermost_service",
    "_login_rate_limiter",
)


class ServiceFactoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {name: getattr(service_factory, name) for name in _SINGLETONS}
        for name in _SINGLETONS:
            setattr(service_factory, name, None)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        for name, value in self._saved.items():
            setattr(service_factory, name, value)

    # -- app-scoped get/set accessors -----------------------------------
    def test_nautobot_accessor_roundtrip(self) -> None:
        with self.assertRaises(RuntimeError):
            service_factory.get_nautobot_app_service()
        svc = MagicMock()
        service_factory.set_nautobot_app_service(svc)
        self.assertIs(service_factory.get_nautobot_app_service(), svc)

    def test_ise_accessor_roundtrip(self) -> None:
        with self.assertRaises(RuntimeError):
            service_factory.get_ise_app_service()
        svc = MagicMock()
        service_factory.set_ise_app_service(svc)
        self.assertIs(service_factory.get_ise_app_service(), svc)

    def test_pyats_and_mattermost_accessors(self) -> None:
        with self.assertRaises(RuntimeError):
            service_factory.get_pyats_app_service()
        with self.assertRaises(RuntimeError):
            service_factory.get_mattermost_app_service()
        p, m = MagicMock(), MagicMock()
        service_factory.set_pyats_app_service(p)
        service_factory.set_mattermost_app_service(m)
        self.assertIs(service_factory.get_pyats_app_service(), p)
        self.assertIs(service_factory.get_mattermost_app_service(), m)

    # -- cache service --------------------------------------------------
    def test_build_cache_service_success_is_memoised(self) -> None:
        with patch("service_factory.RedisCacheService") as cls:
            first = service_factory.build_cache_service()
            second = service_factory.build_cache_service()
        self.assertIs(first, second)
        cls.assert_called_once()

    def test_build_cache_service_returns_none_on_failure(self) -> None:
        with patch("service_factory.RedisCacheService", side_effect=RuntimeError("no redis")):
            self.assertIsNone(service_factory.build_cache_service())

    def test_build_login_rate_limiter_memoised(self) -> None:
        with patch("service_factory.LoginRateLimiter") as cls:
            first = service_factory.build_login_rate_limiter()
            second = service_factory.build_login_rate_limiter()
        self.assertIs(first, second)
        cls.assert_called_once()

    # -- pure builders -----------------------------------------------
    def test_credentials_from_connection_strips_trailing_slash(self) -> None:
        creds = service_factory.credentials_from_connection(
            "https://nb.example.com/", "tok", timeout=10, verify_ssl=False
        )
        self.assertIsInstance(creds, NautobotCredentials)
        self.assertEqual(creds.url, "https://nb.example.com")
        self.assertEqual(creds.timeout, 10)
        self.assertFalse(creds.verify_ssl)

    def test_build_inventory_service(self) -> None:
        from services.sources.nautobot.persistence_service import InventoryService

        self.assertIsInstance(
            service_factory.build_inventory_service(MagicMock()), InventoryService
        )

    def test_config_service_builders(self) -> None:
        from services.ise.source_config_service import ISESourceConfigService
        from services.mattermost.source_config_service import MattermostSourceConfigService
        from services.pyats.source_config_service import PyATSSourceConfigService

        db = MagicMock()
        self.assertIsInstance(
            service_factory.build_ise_source_config_service(db), ISESourceConfigService
        )
        self.assertIsInstance(
            service_factory.build_pyats_source_config_service(db), PyATSSourceConfigService
        )
        self.assertIsInstance(
            service_factory.build_mattermost_source_config_service(db),
            MattermostSourceConfigService,
        )

    def test_ise_network_device_builders_use_app_service(self) -> None:
        from services.ise.network_device_group_service import ISENetworkDeviceGroupService
        from services.ise.network_device_service import ISENetworkDeviceService

        service_factory.set_ise_app_service(MagicMock())
        creds = MagicMock()
        self.assertIsInstance(
            service_factory.build_ise_network_device_service(creds), ISENetworkDeviceService
        )
        self.assertIsInstance(
            service_factory.build_ise_network_device_group_service(creds),
            ISENetworkDeviceGroupService,
        )

    def test_build_nautobot_metadata_service(self) -> None:
        from services.nautobot.metadata_service import NautobotMetadataService

        service_factory.set_nautobot_app_service(MagicMock())
        creds = service_factory.credentials_from_connection("https://x", "t")
        self.assertIsInstance(
            service_factory.build_nautobot_metadata_service(creds), NautobotMetadataService
        )

    def test_build_nautobot_source_service_without_db(self) -> None:
        service_factory.set_nautobot_app_service(MagicMock())
        creds = service_factory.credentials_from_connection("https://x", "t")
        with patch("service_factory.build_cache_service", return_value=None):
            svc = service_factory.build_nautobot_source_service(creds, db=None)
        self.assertIsNone(svc._persistence_service)

    def test_build_nautobot_source_service_uses_configured_ttl_when_enabled(self) -> None:
        service_factory.set_nautobot_app_service(MagicMock())
        creds = service_factory.credentials_from_connection("https://x", "t")
        cache = MagicMock()
        with (
            patch("service_factory.build_cache_service", return_value=cache),
            patch("services.cache.cache_settings_service.CacheSettingsService") as cfg_cls,
        ):
            cfg_cls.return_value.get_settings.return_value = MagicMock(
                enabled=True, device_ttl_seconds=999
            )
            svc = service_factory.build_nautobot_source_service(creds, db=MagicMock())
        self.assertEqual(svc.query_service._bulk_ttl, 999)
        self.assertIs(svc.query_service._cache_service, cache)

    def test_build_nautobot_source_service_disables_cache_when_settings_off(self) -> None:
        service_factory.set_nautobot_app_service(MagicMock())
        creds = service_factory.credentials_from_connection("https://x", "t")
        cache = MagicMock()
        with (
            patch("service_factory.build_cache_service", return_value=cache),
            patch("services.cache.cache_settings_service.CacheSettingsService") as cfg_cls,
        ):
            cfg_cls.return_value.get_settings.return_value = MagicMock(
                enabled=False, device_ttl_seconds=1800
            )
            svc = service_factory.build_nautobot_source_service(creds, db=MagicMock())
        self.assertIsNone(svc.query_service._cache_service)

    # -- lazy git / oidc builders ----------------------------------
    def test_git_builders_return_expected_types(self) -> None:
        from services.git.auth import GitAuthenticationService
        from services.git.connection import GitConnectionService
        from services.git.csv_service import GitCsvService
        from services.git.debug_service import GitDebugService
        from services.git.file_service import GitFileService
        from services.git.operations import GitOperationsService
        from services.git.service import GitService
        from services.git.version_control_service import GitVersionControlService

        self.assertIsInstance(service_factory.build_git_service(), GitService)
        self.assertIsInstance(
            service_factory.build_git_auth_service(), GitAuthenticationService
        )
        self.assertIsInstance(
            service_factory.build_git_operations_service(), GitOperationsService
        )
        self.assertIsInstance(
            service_factory.build_git_connection_service(), GitConnectionService
        )
        self.assertIsInstance(service_factory.build_git_debug_service(), GitDebugService)
        self.assertIsInstance(
            service_factory.build_git_version_control_service(), GitVersionControlService
        )
        self.assertIsInstance(service_factory.build_git_file_service(), GitFileService)
        self.assertIsInstance(service_factory.build_git_csv_service(), GitCsvService)

    def test_build_git_cache_service_wires_cache(self) -> None:
        from services.git.cache import GitCacheService

        sentinel = object()
        with patch("service_factory.build_cache_service", return_value=sentinel):
            svc = service_factory.build_git_cache_service()
        self.assertIsInstance(svc, GitCacheService)
        self.assertIs(svc._cache, sentinel)

    def test_build_credentials_service_uses_passed_session(self) -> None:
        from services.credentials.credentials_service import CredentialsService

        svc = service_factory.build_credentials_service(MagicMock())
        self.assertIsInstance(svc, CredentialsService)

    def test_oidc_builders(self) -> None:
        from services.auth.oidc_config_service import OidcConfigService
        from services.auth.oidc_service import OIDCService

        self.assertIsInstance(
            service_factory.build_oidc_config_service(), OidcConfigService
        )
        self.assertIsInstance(service_factory.build_oidc_service(), OIDCService)


if __name__ == "__main__":
    unittest.main()

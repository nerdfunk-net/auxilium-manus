"""Tests for OidcConfigService's YAML loading/parsing behavior."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.auth.oidc_config_service import OidcConfigService


class OidcConfigServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.config_path = Path(self._tmpdir.name) / "oidc_providers.yaml"

    def _write(self, content: str) -> OidcConfigService:
        self.config_path.write_text(content, encoding="utf-8")
        return OidcConfigService(self.config_path)

    def test_missing_file_returns_empty_config(self) -> None:
        service = OidcConfigService(self.config_path)

        self.assertEqual(service.get_providers(), {})
        self.assertTrue(service.get_global_settings()["allow_traditional_login"])
        self.assertFalse(service.is_enabled())

    def test_enabled_providers_sorted_by_display_order(self) -> None:
        service = self._write(
            """
providers:
  second:
    enabled: true
    display_order: 2
    discovery_url: "https://example.com/second"
    client_id: "second-client"
    client_secret: "secret"
  first:
    enabled: true
    display_order: 1
    discovery_url: "https://example.com/first"
    client_id: "first-client"
    client_secret: "secret"
  disabled:
    enabled: false
    discovery_url: "https://example.com/disabled"
    client_id: "disabled-client"
    client_secret: "secret"
global:
  allow_traditional_login: false
"""
        )

        enabled = service.get_enabled_providers()

        self.assertEqual([p["provider_id"] for p in enabled], ["first", "second"])
        self.assertFalse(service.get_global_settings()["allow_traditional_login"])
        self.assertTrue(service.is_enabled())

    def test_get_provider_returns_none_for_unknown_id(self) -> None:
        service = self._write("providers: {}\n")

        self.assertIsNone(service.get_provider("nonexistent"))

    def test_get_provider_includes_provider_id(self) -> None:
        service = self._write(
            """
providers:
  corporate:
    enabled: true
    discovery_url: "https://example.com"
    client_id: "corp"
    client_secret: "secret"
"""
        )

        provider = service.get_provider("corporate")

        self.assertIsNotNone(provider)
        assert provider is not None
        self.assertEqual(provider["provider_id"], "corporate")

    def test_malformed_yaml_falls_back_to_empty_config(self) -> None:
        service = self._write("providers: [this, is, not, a, mapping]\n")

        self.assertEqual(service.get_providers(), {})

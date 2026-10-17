"""PluginRegistryService.get_plugin_config loads a plugin's config.py::get_config()."""

from __future__ import annotations

import unittest
from pathlib import Path

from repositories.plugin_repository import PluginRepository
from services.plugin_registry.plugin_registry_service import PluginRegistryService

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "workflow_steps" / "registry.yaml"


class PluginConfigLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = PluginRegistryService(PluginRepository(REGISTRY_PATH))

    def test_returns_config_dict_for_plugin_with_config_module(self) -> None:
        cfg = self.service.get_plugin_config("run-command")
        self.assertIsInstance(cfg, dict)

    def test_returns_empty_dict_for_plugin_without_config_module(self) -> None:
        cfg = self.service.get_plugin_config("funnel")
        self.assertEqual(cfg, {})

    def test_returns_none_for_unknown_plugin(self) -> None:
        self.assertIsNone(self.service.get_plugin_config("does-not-exist"))


if __name__ == "__main__":
    unittest.main()

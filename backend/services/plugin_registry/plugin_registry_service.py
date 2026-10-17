from __future__ import annotations

import importlib.util
import logging
from typing import Any

from pydantic import ValidationError

from models.plugins import PluginDefinition, PluginRegistry
from repositories.plugin_repository import PluginRepository, PluginRepositoryError

logger = logging.getLogger(__name__)


class PluginRegistryError(RuntimeError):
    """Raised when plugin registry data is invalid."""


class PluginRegistryService:
    def __init__(self, repository: PluginRepository) -> None:
        self.repository = repository
        self._registry: PluginRegistry | None = None

    def load_registry(self) -> PluginRegistry:
        try:
            registry = PluginRegistry.model_validate(self.repository.load_registry_data())
        except (PluginRepositoryError, ValidationError) as exc:
            raise PluginRegistryError("Plugin registry could not be loaded") from exc

        self._validate_unique_plugins(registry)
        self._registry = registry

        return registry

    def get_registry(self) -> PluginRegistry:
        if self._registry is None:
            return self.load_registry()

        return self._registry

    def list_plugins(self, include_disabled: bool = False) -> list[PluginDefinition]:
        plugins = self.get_registry().plugins

        if include_disabled:
            return plugins

        return [plugin for plugin in plugins if plugin.enabled]

    def get_plugin(
        self,
        plugin_id: str,
        include_disabled: bool = False,
    ) -> PluginDefinition | None:
        return next(
            (
                plugin
                for plugin in self.get_registry().plugins
                if plugin.id == plugin_id and (include_disabled or plugin.enabled)
            ),
            None,
        )

    def get_plugin_config(self, plugin_id: str) -> dict[str, Any] | None:
        """Return a plugin's ``config.py::get_config()`` result.

        ``None`` means the plugin id is unknown (caller raises 404); ``{}``
        means the plugin has no config module, or its ``get_config()`` failed
        or returned something other than a dict.
        """
        plugin = self.get_plugin(plugin_id)
        if plugin is None:
            return None

        config_path = self.repository.plugins_file.parent / plugin.directory / "config.py"
        if not config_path.is_file():
            return {}

        module_name = f"workflow_steps.{plugin.directory}.config"
        spec = importlib.util.spec_from_file_location(module_name, config_path)
        if spec is None or spec.loader is None:
            logger.warning("Cannot load config module for plugin '%s'", plugin_id)
            return {}

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        get_config = getattr(module, "get_config", None)
        if not callable(get_config):
            return {}
        try:
            cfg = get_config()
        except Exception:
            logger.exception("get_config() failed for plugin '%s'", plugin_id)
            return {}
        if not isinstance(cfg, dict):
            return {}
        return cfg

    @staticmethod
    def _validate_unique_plugins(registry: PluginRegistry) -> None:
        plugin_ids = [plugin.id for plugin in registry.plugins]

        if len(plugin_ids) != len(set(plugin_ids)):
            raise PluginRegistryError("Plugin ids must be unique")

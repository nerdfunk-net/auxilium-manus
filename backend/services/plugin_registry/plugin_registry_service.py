from __future__ import annotations

from pydantic import ValidationError

from models.plugins import PluginDefinition, PluginRegistry
from repositories.plugin_repository import PluginRepository, PluginRepositoryError


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

    @staticmethod
    def _validate_unique_plugins(registry: PluginRegistry) -> None:
        plugin_ids = [plugin.id for plugin in registry.plugins]

        if len(plugin_ids) != len(set(plugin_ids)):
            raise PluginRegistryError("Plugin ids must be unique")

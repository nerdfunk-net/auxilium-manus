from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class PluginRepositoryError(RuntimeError):
    """Raised when the plugin registry file cannot be loaded."""


class PluginRepository:
    def __init__(self, plugins_file: Path) -> None:
        self.plugins_file = plugins_file

    def load_registry_data(self) -> dict[str, Any]:
        if not self.plugins_file.exists():
            raise PluginRepositoryError("Plugin registry file does not exist")

        with self.plugins_file.open("r", encoding="utf-8") as registry_file:
            registry_data = yaml.safe_load(registry_file) or {}

        if not isinstance(registry_data, dict):
            raise PluginRepositoryError("Plugin registry root must be a mapping")

        return registry_data

"""Loads OIDC provider configuration from config/oidc_providers.yaml.

Pure file-based reader, no database — mirrors the pattern used for other
filesystem-backed admin config (see CertificateService). Re-reads and
re-parses the YAML on every call; acceptable since this is low-frequency
admin config, not a request-hot path.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from core.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

OIDC_CONFIG_PATH = PROJECT_ROOT / "config" / "oidc_providers.yaml"

_EMPTY_CONFIG: dict[str, Any] = {
    "providers": {},
    "global": {"allow_traditional_login": True},
}


class OidcConfigService:
    def __init__(self, config_path: Path = OIDC_CONFIG_PATH) -> None:
        self._config_path = config_path

    def get_config_path(self) -> Path:
        return self._config_path

    def load_providers(self) -> dict[str, Any]:
        if not self._config_path.exists():
            return _EMPTY_CONFIG

        try:
            with self._config_path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError):
            logger.exception("Failed to load OIDC provider config from %s", self._config_path)
            return _EMPTY_CONFIG

        if not isinstance(data, dict) or not isinstance(data.get("providers", {}), dict):
            logger.error(
                "OIDC provider config at %s is malformed (expected a 'providers' mapping)",
                self._config_path,
            )
            return _EMPTY_CONFIG

        data.setdefault("providers", {})
        data.setdefault("global", {"allow_traditional_login": True})
        return data

    def get_providers(self) -> dict[str, dict[str, Any]]:
        return self.load_providers().get("providers", {})

    def get_enabled_providers(self) -> list[dict[str, Any]]:
        providers = self.get_providers()
        enabled = []

        for provider_id, config in providers.items():
            if not config.get("enabled", False):
                continue
            enabled.append({**config, "provider_id": provider_id})

        return sorted(enabled, key=lambda item: item.get("display_order", 999))

    def get_provider(self, provider_id: str) -> dict[str, Any] | None:
        provider = self.get_providers().get(provider_id)
        if provider is None:
            return None
        return {**provider, "provider_id": provider_id}

    def get_global_settings(self) -> dict[str, Any]:
        return self.load_providers().get("global", {"allow_traditional_login": True})

    def is_enabled(self) -> bool:
        return len(self.get_enabled_providers()) > 0

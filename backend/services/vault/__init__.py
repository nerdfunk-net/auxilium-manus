"""OpenBao (Vault) integration package.

Public surface: :class:`OpenBaoService` (the sync KV v2 client) and
:class:`VaultConfig`. Construct instances via :mod:`core.vault`; hold them as
singletons in :mod:`service_factory`. See ``doc/VAULT_INTEGRATION.md``.
"""

from __future__ import annotations

from services.vault.client import OpenBaoService
from services.vault.config import VaultConfig
from services.vault.exceptions import (
    VaultAuthError,
    VaultConfigError,
    VaultError,
    VaultPermissionError,
    VaultSecretNotFoundError,
    VaultUnavailableError,
)

__all__ = [
    "OpenBaoService",
    "VaultConfig",
    "VaultError",
    "VaultConfigError",
    "VaultAuthError",
    "VaultUnavailableError",
    "VaultPermissionError",
    "VaultSecretNotFoundError",
]

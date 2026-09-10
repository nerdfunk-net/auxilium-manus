"""OpenBao (Vault) client exception hierarchy.

Every failure that a resolver seam must fail *closed* on is a ``VaultError``
subclass so callers can catch the base type and refuse to serve a secret rather
than fall back to a stale or empty value.
"""

from __future__ import annotations


class VaultError(Exception):
    """Base exception for all OpenBao client operations."""


class VaultConfigError(VaultError):
    """Raised when the vault configuration is missing or structurally invalid."""


class VaultAuthError(VaultError):
    """Raised when authenticating to OpenBao fails (bad RoleID/SecretID/cert)."""


class VaultUnavailableError(VaultError):
    """Raised when OpenBao is unreachable, sealed, or returns a 5xx."""


class VaultPermissionError(VaultError):
    """Raised when the current token is denied access to a path (HTTP 403)."""


class VaultSecretNotFoundError(VaultError):
    """Raised when the requested KV path holds no secret (HTTP 404)."""

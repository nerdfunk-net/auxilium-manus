"""Secret Manager exception hierarchy.

Mirrors ``services.vault.exceptions.VaultError`` — every failure that a
resolver seam must fail *closed* on is a ``SecretManagerError`` subclass so
callers refuse to serve/store a secret rather than fall back to a stale or
empty value.
"""

from __future__ import annotations


class SecretManagerError(Exception):
    """Base exception for all secret manager client operations."""


class SecretManagerConfigError(SecretManagerError):
    """Raised when a connection's configuration is missing or invalid."""


class SecretManagerAuthError(SecretManagerError):
    """Raised when authenticating to the backend fails."""


class SecretManagerUnavailableError(SecretManagerError):
    """Raised when the backend is unreachable or returns a 5xx."""


class SecretManagerPermissionError(SecretManagerError):
    """Raised when the current session is denied access to a path (HTTP 403)."""


class SecretManagerFieldNotFoundError(SecretManagerError):
    """Raised when the requested path/field holds no secret (HTTP 404)."""

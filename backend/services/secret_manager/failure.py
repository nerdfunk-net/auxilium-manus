"""Failure classification of Secret Manager client errors (next to the client)."""

from __future__ import annotations

from models.failure import FailureInfo
from services.secret_manager.exceptions import (
    SecretManagerAuthError,
    SecretManagerError,
    SecretManagerPermissionError,
    SecretManagerUnavailableError,
)


def secret_manager_failure(exc: SecretManagerError) -> FailureInfo:
    """Closed-vocabulary classification of a Secret Manager client error."""
    if isinstance(exc, SecretManagerAuthError):
        return FailureInfo(phase="auth", kind="auth_failed", exception_type=type(exc).__name__)
    if isinstance(exc, SecretManagerPermissionError):
        return FailureInfo(phase="api", kind="permission_denied", exception_type=type(exc).__name__)
    if isinstance(exc, SecretManagerUnavailableError):
        return FailureInfo(
            phase="api", kind="server_error", retryable=True, exception_type=type(exc).__name__
        )
    return FailureInfo(phase="api", kind="unknown", exception_type=type(exc).__name__)

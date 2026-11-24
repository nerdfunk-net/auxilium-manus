"""The closed-vocabulary classification of Secret Manager client errors."""

from __future__ import annotations

import pytest

from services.secret_manager.exceptions import (
    SecretManagerAuthError,
    SecretManagerError,
    SecretManagerPermissionError,
    SecretManagerUnavailableError,
)
from services.secret_manager.failure import secret_manager_failure


@pytest.mark.parametrize(
    ("error", "phase", "kind", "retryable"),
    [
        (SecretManagerAuthError("token rejected for s3cret"), "auth", "auth_failed", False),
        (SecretManagerPermissionError("no"), "api", "permission_denied", False),
        (SecretManagerUnavailableError("down"), "api", "server_error", True),
        (SecretManagerError("other"), "api", "unknown", False),
    ],
)
def test_classes_map_to_a_record_without_the_message(
    error: SecretManagerError, phase: str, kind: str, retryable: bool
) -> None:
    info = secret_manager_failure(error)
    assert (info.phase, info.kind, info.retryable) == (phase, kind, retryable)
    assert info.exception_type == type(error).__name__
    assert "s3cret" not in info.model_dump_json()

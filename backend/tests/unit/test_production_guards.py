"""S6-05 / S3-08 / S1-04: guards refuse what makes a key guessable, warn about relaxations."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.production_guards import collect_startup_warnings, validate_non_development_secrets

GOOD = {
    "environment": "production",
    "secret_key": "s" * 40,
    "initial_password": "i" * 14,
    "credential_encryption_key": "c" * 32,
    "database_password": "strong-db-password-1",
    "redis_password": "strong-redis-password-1",
}


def _validate(**override: object) -> None:
    validate_non_development_secrets(**{**GOOD, **override})  # type: ignore[arg-type]


def test_strong_values_pass() -> None:
    _validate()


@pytest.mark.parametrize(
    "key", ["a", "Winter2026!", "change-in-production-use-at-least-32-characters", "c" * 31]
)
def test_weak_credential_encryption_key_is_refused(key: str) -> None:
    with pytest.raises(RuntimeError):
        _validate(credential_encryption_key=key)


@pytest.mark.parametrize("password", ["changeme", "admin", "postgres", "short", "x" * 11])
def test_weak_database_password_is_refused(password: str) -> None:
    with pytest.raises(RuntimeError):
        _validate(database_password=password)


@pytest.mark.parametrize("password", ["1", "changeme", "redis", "x" * 11])
def test_weak_redis_password_is_refused(password: str) -> None:
    with pytest.raises(RuntimeError):
        _validate(redis_password=password)


def test_startup_warnings() -> None:
    kwargs = {
        "docs_enabled": True,
        "allow_loopback_source_urls": True,
        "max_request_body_bytes": 0,
    }
    assert len(collect_startup_warnings(environment="production", **kwargs)) == 3
    assert collect_startup_warnings(environment="development", **kwargs) == []
    assert (
        collect_startup_warnings(
            environment="production",
            docs_enabled=False,
            allow_loopback_source_urls=False,
            max_request_body_bytes=1,
        )
        == []
    )


def _import_config(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    backend = Path(__file__).resolve().parents[2]
    dropped = {"ENV", "SECRET_KEY", "KDF_ITERATIONS"}
    clean = {k: v for k, v in os.environ.items() if k not in dropped}
    clean.update(env)
    clean["HOME"] = str(backend)  # never pick up a developer's files
    clean["MANUS_ENV_FILE"] = os.devnull  # nor backend/.env
    return subprocess.run(
        [sys.executable, "-W", "ignore", "-c", "import core.config"],
        cwd=backend,
        env=clean,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_env_unset_means_production() -> None:
    result = _import_config({"SECRET_KEY": "change-in-production-use-at-least-32-characters"})
    assert result.returncode != 0
    assert "SECRET_KEY must be configured outside development" in result.stderr


def test_env_development_is_explicit() -> None:
    result = _import_config({"ENV": "development"})
    assert result.returncode == 0, result.stderr


def test_worker_role_does_not_require_manage_role_or_initial_password() -> None:
    vault = {
        "vault_enabled": True,
        "vault_addr": "https://bao.example:8200",
        "vault_role_id": "role",
        "vault_secret_id": "secret",
    }
    with pytest.raises(RuntimeError, match="VAULT_MANAGE_ROLE_ID"):
        _validate(**vault)
    _validate(**vault, process_role="worker", initial_password="admin")
    with pytest.raises(RuntimeError, match="INITIAL_PASSWORD"):
        _validate(initial_password="admin")

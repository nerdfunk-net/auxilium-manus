"""Release gate (HOWTO section 8): production startup rejects every insecure default of S1/S3/S6.

Each case starts the real ``core.config.Settings`` with ``ENV=production`` and one value changed
from a strong baseline (the method of S6-05), so a guard that exists but is not wired through
``Settings`` fails here too. ``test_production_guards.py`` and ``test_vault_config_guards.py`` test
the guard functions on their own; this file tests the whole startup path.

Not covered on purpose: long values that are merely guessable (32 identical characters, a common
password of 12+ characters). The guard checks length and a list of repository defaults, not entropy.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from core import crypto_policy
from core.config import Settings
from core.production_guards import DEFAULT_SECRET_KEY

PRODUCTION_KDF_FLOOR = 600_000

STRONG_ENV = {
    "ENV": "production",
    "SECRET_KEY": "a1" * 20,
    "INITIAL_PASSWORD": "Str0ng-Initial-pw",
    "CREDENTIAL_ENCRYPTION_KEY": "b2" * 20,
    "DATABASE_PASSWORD": "db-pass-0123456789abcdef",
    "MANUS_REDIS_PASSWORD": "redis-pass-0123456789abcdef",
    "TRUSTED_PROXY_IPS": "127.0.0.1",
}

# Every setting a case below can touch; cleared first so the developer's shell cannot leak in.
CONTROLLED = (
    *STRONG_ENV,
    "ENABLE_DEV_TOOLS",
    "ALLOW_NETMIKO_ARBITRARY_HOSTS",
    "KDF_ITERATIONS",
    "ACCESS_TOKEN_EXPIRE_MINUTES",
    "AI_ALLOWED_PROVIDERS",
    "AI_ALLOWED_DATA",
    "AI_ASSISTANT_ENABLED",
    "DOCS_ENABLED",
    "ALLOW_LOOPBACK_SOURCE_URLS",
    "MAX_REQUEST_BODY_BYTES",
    "MANUS_PROCESS_ROLE",
    "VAULT_ENABLED",
    "VAULT_ADDR",
    "VAULT_VERIFY_SSL",
    "VAULT_AUTH_METHOD",
    "VAULT_TOKEN",
    "VAULT_ROLE_ID",
    "VAULT_SECRET_ID",
    "VAULT_SECRET_ID_FILE",
    "VAULT_MANAGE_ROLE_ID",
    "VAULT_MANAGE_SECRET_ID",
    "VAULT_MANAGE_SECRET_ID_FILE",
)

VAULT_OK = {
    "VAULT_ENABLED": "true",
    "VAULT_ADDR": "https://bao.example.test:8200",
    "VAULT_ROLE_ID": "role",
    "VAULT_SECRET_ID": "secret",
    "VAULT_MANAGE_ROLE_ID": "manage-role",
    "VAULT_MANAGE_SECRET_ID": "manage-secret",
}


@pytest.fixture
def start(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Return a function that builds ``Settings`` from the strong baseline plus overrides.

    A value of ``None`` removes the variable."""

    def _start(overrides: dict[str, str | None] | None = None) -> Settings:
        # tests/conftest.py lowers the KDF floor so the suite stays fast; this file checks the
        # production value.
        monkeypatch.setattr(crypto_policy, "KDF_ITERATIONS_FLOOR", PRODUCTION_KDF_FLOOR)
        for name in CONTROLLED:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("DATA_DIRECTORY", str(tmp_path / "data"))
        monkeypatch.setenv("LOG_DIRECTORY", str(tmp_path / "logs"))
        for name, value in {**STRONG_ENV, **(overrides or {})}.items():
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        return Settings()

    return _start


def test_the_strong_baseline_starts(start) -> None:
    assert start().environment == "production"


def test_the_kdf_floor_in_the_source_is_the_production_value() -> None:
    """``tests/conftest.py`` overrides the constant at runtime, so read it from the file."""
    source = Path(crypto_policy.__file__).read_text()
    match = re.search(r"^KDF_ITERATIONS_FLOOR\s*=\s*([\d_]+)", source, re.MULTILINE)
    assert match is not None
    assert int(match.group(1).replace("_", "")) == PRODUCTION_KDF_FLOOR


# (label, overrides, text the refusal must contain)
REFUSED = [
    # S1-04: the default environment is production, so a missing configuration cannot start.
    ("ENV unset and no secrets", {k: None for k in STRONG_ENV}, "SECRET_KEY must be configured"),
    # SECRET_KEY
    ("SECRET_KEY repository default", {"SECRET_KEY": DEFAULT_SECRET_KEY}, "SECRET_KEY"),
    ("SECRET_KEY unset", {"SECRET_KEY": None}, "SECRET_KEY"),
    ("SECRET_KEY 31 characters", {"SECRET_KEY": "k" * 31}, "at least 32"),
    # INITIAL_PASSWORD
    ("INITIAL_PASSWORD admin", {"INITIAL_PASSWORD": "admin"}, "INITIAL_PASSWORD"),
    ("INITIAL_PASSWORD too short", {"INITIAL_PASSWORD": "short"}, "at least 12"),
    # S3-08 CREDENTIAL_ENCRYPTION_KEY
    ("CREDENTIAL_ENCRYPTION_KEY unset", {"CREDENTIAL_ENCRYPTION_KEY": None}, "CREDENTIAL_ENC"),
    ("CREDENTIAL_ENCRYPTION_KEY a", {"CREDENTIAL_ENCRYPTION_KEY": "a"}, "at least 32"),
    (
        "CREDENTIAL_ENCRYPTION_KEY Winter2026!",
        {"CREDENTIAL_ENCRYPTION_KEY": "Winter2026!"},
        "at least 32",
    ),
    (
        "CREDENTIAL_ENCRYPTION_KEY repository default",
        {"CREDENTIAL_ENCRYPTION_KEY": DEFAULT_SECRET_KEY},
        "CREDENTIAL_ENCRYPTION_KEY",
    ),
    (
        "CREDENTIAL_ENCRYPTION_KEY equals SECRET_KEY",
        {"CREDENTIAL_ENCRYPTION_KEY": "a1" * 20},
        "must differ",
    ),
    # S6-05 database and Redis passwords
    ("DATABASE_PASSWORD empty", {"DATABASE_PASSWORD": ""}, "DATABASE_PASSWORD"),
    ("DATABASE_PASSWORD postgres", {"DATABASE_PASSWORD": "postgres"}, "DATABASE_PASSWORD"),
    ("DATABASE_PASSWORD changeme", {"DATABASE_PASSWORD": "changeme"}, "known default"),
    ("DATABASE_PASSWORD admin", {"DATABASE_PASSWORD": "admin"}, "known default"),
    ("DATABASE_PASSWORD 11 characters", {"DATABASE_PASSWORD": "short-pw-11"}, "at least 12"),
    ("MANUS_REDIS_PASSWORD unset", {"MANUS_REDIS_PASSWORD": None}, "MANUS_REDIS_PASSWORD"),
    ("MANUS_REDIS_PASSWORD 1", {"MANUS_REDIS_PASSWORD": "1"}, "at least 12"),
    ("MANUS_REDIS_PASSWORD changeme", {"MANUS_REDIS_PASSWORD": "changeme"}, "known default"),
    ("MANUS_REDIS_PASSWORD secret", {"MANUS_REDIS_PASSWORD": "secret"}, "known default"),
    # development switches
    ("ENABLE_DEV_TOOLS", {"ENABLE_DEV_TOOLS": "true"}, "ENABLE_DEV_TOOLS"),
    (
        "ALLOW_NETMIKO_ARBITRARY_HOSTS",
        {"ALLOW_NETMIKO_ARBITRARY_HOSTS": "true"},
        "ALLOW_NETMIKO_ARBITRARY_HOSTS",
    ),
    # S1-02 proxy trust
    ("TRUSTED_PROXY_IPS unset", {"TRUSTED_PROXY_IPS": None}, "TRUSTED_PROXY_IPS must be set"),
    ("TRUSTED_PROXY_IPS 0.0.0.0/0", {"TRUSTED_PROXY_IPS": "0.0.0.0/0"}, "catch-all"),
    ("TRUSTED_PROXY_IPS ::/0", {"TRUSTED_PROXY_IPS": "::/0"}, "catch-all"),
    ("TRUSTED_PROXY_IPS 0.0.0.0", {"TRUSTED_PROXY_IPS": "0.0.0.0"}, "unspecified"),
    ("TRUSTED_PROXY_IPS invalid", {"TRUSTED_PROXY_IPS": "not-an-ip"}, "invalid IP"),
    # S3-09 / S1-14 numeric settings
    ("KDF_ITERATIONS 1000", {"KDF_ITERATIONS": "1000"}, "KDF_ITERATIONS"),
    ("KDF_ITERATIONS old default 100000", {"KDF_ITERATIONS": "100000"}, "KDF_ITERATIONS"),
    ("ACCESS_TOKEN_EXPIRE_MINUTES 0", {"ACCESS_TOKEN_EXPIRE_MINUTES": "0"}, "between 1 and 1440"),
    ("ACCESS_TOKEN_EXPIRE_MINUTES -5", {"ACCESS_TOKEN_EXPIRE_MINUTES": "-5"}, "between 1"),
    ("ACCESS_TOKEN_EXPIRE_MINUTES huge", {"ACCESS_TOKEN_EXPIRE_MINUTES": "100000"}, "1440"),
    # S6-15 operator switches: a typo must not silently change what a model may see
    ("AI_ALLOWED_PROVIDERS typo", {"AI_ALLOWED_PROVIDERS": "anthropicc"}, "AI_ALLOWED_PROVIDERS"),
    ("AI_ALLOWED_DATA typo", {"AI_ALLOWED_DATA": "everything"}, "AI_ALLOWED_DATA"),
    # OpenBao
    ("VAULT_ADDR over http", {**VAULT_OK, "VAULT_ADDR": "http://bao:8200"}, "must use https"),
    ("VAULT_VERIFY_SSL false", {**VAULT_OK, "VAULT_VERIFY_SSL": "false"}, "VAULT_VERIFY_SSL"),
    (
        "VAULT_AUTH_METHOD token",
        {**VAULT_OK, "VAULT_AUTH_METHOD": "token", "VAULT_TOKEN": "t"},
        "only allowed in development",
    ),
    ("VAULT_ROLE_ID missing", {**VAULT_OK, "VAULT_ROLE_ID": None}, "VAULT_ROLE_ID"),
    ("VAULT_SECRET_ID missing", {**VAULT_OK, "VAULT_SECRET_ID": None}, "VAULT_SECRET_ID"),
    (
        "management role missing on the web process",
        {**VAULT_OK, "VAULT_MANAGE_ROLE_ID": None},
        "VAULT_MANAGE_ROLE_ID",
    ),
]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [pytest.param(o, m, id=label) for label, o, m in REFUSED],
)
def test_insecure_production_configuration_is_refused(start, overrides, message) -> None:
    with pytest.raises(RuntimeError, match=message):
        start(overrides)


def test_openbao_with_a_valid_https_approle_configuration_starts(start) -> None:
    assert start(VAULT_OK).environment == "production"


def test_a_worker_needs_neither_initial_password_nor_management_role(start) -> None:
    settings = start(
        {
            **VAULT_OK,
            "MANUS_PROCESS_ROLE": "worker",
            "INITIAL_PASSWORD": "admin",
            "VAULT_MANAGE_ROLE_ID": None,
            "VAULT_MANAGE_SECRET_ID": None,
        }
    )
    assert settings.environment == "production"


def test_development_is_an_explicit_choice_and_skips_the_guards(start) -> None:
    settings = start({"ENV": "development", "SECRET_KEY": "x", "DATABASE_PASSWORD": "postgres"})
    assert settings.environment == "development"


@pytest.mark.parametrize(
    ("variable", "value", "expected"),
    [
        ("DOCS_ENABLED", "true", "DOCS_ENABLED"),
        ("ALLOW_LOOPBACK_SOURCE_URLS", "true", "ALLOW_LOOPBACK_SOURCE_URLS"),
        ("MAX_REQUEST_BODY_BYTES", "0", "MAX_REQUEST_BODY_BYTES"),
    ],
)
def test_deliberate_relaxations_start_with_a_warning(
    start, caplog: pytest.LogCaptureFixture, variable: str, value: str, expected: str
) -> None:
    with caplog.at_level(logging.WARNING, logger="core.config"):
        settings = start({variable: value})
    assert settings.environment == "production"
    assert any(expected in record.getMessage() for record in caplog.records)


def test_a_clean_production_start_logs_no_relaxation_warning(
    start, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="core.config"):
        start()
    assert not [r for r in caplog.records if "Startup configuration" in r.getMessage()]

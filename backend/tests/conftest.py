"""Ensure ``backend/`` is on ``sys.path`` so ``core.*`` / ``services.*`` import.

Allows pytest to be started from either ``backend/`` or the repo root.
Loaded for both ``tests/unit`` and ``tests/integration``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_backend_str = str(_BACKEND_ROOT)
if _backend_str not in sys.path:
    sys.path.insert(0, _backend_str)

# hatchet_sdk.Hatchet() (constructed at import time by hatchet/client.py and by
# every hatchet/workflows/*.py module that calls hatchet.workflow(...) at module
# scope) requires a syntactically valid JWT in HATCHET_CLIENT_TOKEN — it decodes
# the payload locally (sub/server_url/grpc_broadcast_address) but never makes a
# network call or verifies the signature. CI has no .env, so without this, any
# test that transitively imports a hatchet.* module fails at collection with
# "Token must be set". setdefault() leaves a real dev token (loaded from .env
# later by core/config.py) untouched if one is already present.
os.environ.setdefault(
    "HATCHET_CLIENT_TOKEN",
    "eyJhbGciOiAibm9uZSIsICJ0eXAiOiAiSldUIn0."
    "eyJzdWIiOiAidGVzdC10ZW5hbnQiLCAic2VydmVyX3VybCI6ICJodHRwOi8vbG9jYWxob3N0OjgwODAiLCAi"
    "Z3JwY19icm9hZGNhc3RfYWRkcmVzcyI6ICJsb2NhbGhvc3Q6NzA3NyJ9."
    "dW5pdC10ZXN0LXNpZ25hdHVyZS1ub3QtdmVyaWZpZWQ",
)

# core.crypto.resolve_credential_secret() reads CREDENTIAL_ENCRYPTION_KEY / SECRET_KEY
# straight from os.getenv (bypassing core.config.settings' own DEFAULT_SECRET_KEY
# fallback), so credential-encryption tests need a raw env var, not just a Settings
# default. CI has no .env; locally .env already sets this (see .env.example).
# Development is an explicit choice (ENV defaults to production); tests run as a developer would.
os.environ.setdefault("ENV", "development")
# The AI assistant is off for operators by default; the suite exercises it, so it opts in.
os.environ.setdefault("AI_ASSISTANT_ENABLED", "true")
os.environ.setdefault("AI_ALLOWED_PROVIDERS", "anthropic,gemini,openai_compat")
os.environ.setdefault(
    "AI_ALLOWED_DATA", "inventory,addresses,custom_fields,config_context,content,report"
)

# The production KDF floor (600k PBKDF2 iterations) would make every test that builds an
# EncryptionService pay ~0.3 s. The suite lowers the floor *before* core.config is imported;
# tests of the floor itself (test_crypto.py) set it back explicitly.
from core import crypto_policy as _crypto_policy  # noqa: E402

TEST_KDF_ITERATIONS = 1_000
_crypto_policy.KDF_ITERATIONS_FLOOR = TEST_KDF_ITERATIONS
os.environ.setdefault("KDF_ITERATIONS", str(TEST_KDF_ITERATIONS))
os.environ.setdefault("SECRET_KEY", "change-in-production-use-at-least-32-characters")

# core.safe_urls blocks loopback targets unless ALLOW_LOOPBACK_SOURCE_URLS=true; unit
# tests exercise outbound HTTP clients (Mattermost, git) against local mock servers on
# 127.0.0.1/::1, so the guard must be relaxed the same way local .env already does.
os.environ.setdefault("ALLOW_LOOPBACK_SOURCE_URLS", "true")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_user_rate_limiters(monkeypatch):
    """Per-user rate-limit buckets (S9) are process-global and, with a reachable dev Redis,
    would also persist across tests and runs. Reset them and point them at an unreachable
    Redis so the in-process fallback window does the counting."""
    import service_factory
    from services.auth.login_rate_limiter import LoginRateLimiter

    service_factory._user_rate_limiters.clear()

    def build(bucket: str, attempts: int, window_seconds: int) -> LoginRateLimiter:
        limiter = service_factory._user_rate_limiters.get(bucket)
        if limiter is None:
            limiter = service_factory._user_rate_limiters[bucket] = LoginRateLimiter(
                redis_url="redis://127.0.0.1:1/0",
                key_prefix=f"manus-rl-test:{bucket}",
                fail_closed=False,
                attempts=attempts,
                window_seconds=window_seconds,
            )
        return limiter

    monkeypatch.setattr(service_factory, "build_user_rate_limiter", build)
    yield
    service_factory._user_rate_limiters.clear()


@pytest.fixture(autouse=True)
def _closed_dispatch_breaker():
    """The Hatchet dispatch breaker is process-global; a test that fails a dispatch must not make
    the next test's dispatch fail at once."""
    from services.execution.dispatch_breaker import dispatch_breaker

    dispatch_breaker.reset()
    yield
    dispatch_breaker.reset()


# The ``settings`` table is JSONB; unit tests build it on in-memory SQLite, which has no JSONB.
@compiles(JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(_type: JSONB, _compiler: object, **_kw: object) -> str:
    return "JSON"

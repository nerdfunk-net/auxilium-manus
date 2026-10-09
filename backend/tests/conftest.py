"""Ensure ``backend/`` is on ``sys.path`` so ``core.*`` / ``services.*`` import.

Allows pytest to be started from either ``backend/`` or the repo root.
Loaded for both ``tests/unit`` and ``tests/integration``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

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

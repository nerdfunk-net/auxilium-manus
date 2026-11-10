"""Operator settings for the DNS tool: parsed and validated at startup."""

from __future__ import annotations

import pytest

from core.config import Settings


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key in ("AI_DNS_LOOKUP_ENABLED", "AI_DNS_ALLOWED_SUFFIXES"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings()


def test_dns_lookup_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings(monkeypatch)
    assert s.ai_dns_lookup_enabled is False
    assert s.ai_dns_allowed_suffixes == ()


def test_suffixes_are_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings(
        monkeypatch,
        AI_DNS_LOOKUP_ENABLED="true",
        AI_DNS_ALLOWED_SUFFIXES=" .Local.ZZ, corp.example.",
    )
    assert s.ai_dns_lookup_enabled is True
    assert s.ai_dns_allowed_suffixes == ("corp.example", "local.zz")


def test_a_bad_suffix_refuses_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="AI_DNS_ALLOWED_SUFFIXES"):
        _settings(monkeypatch, AI_DNS_ALLOWED_SUFFIXES="ok.zz,not valid")


def test_a_one_label_suffix_is_refused() -> None:
    import pytest as _pytest

    from core.dns_names import normalize_suffix

    with _pytest.raises(ValueError):
        normalize_suffix("com")

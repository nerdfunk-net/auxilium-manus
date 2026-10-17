"""Unit tests for core.ssl_config — the shared outbound-TLS trust context."""

from __future__ import annotations

import ssl

import httpx
import pytest

from core import ssl_config


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    ssl_config.create_verified_ssl_context.cache_clear()
    yield
    ssl_config.create_verified_ssl_context.cache_clear()


def test_returns_verifying_context() -> None:
    context = ssl_config.create_verified_ssl_context()

    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_context_has_ca_certificates_loaded() -> None:
    context = ssl_config.create_verified_ssl_context()

    # certifi alone guarantees a non-empty CA store, independent of the OS store.
    assert context.cert_store_stats()["x509_ca"] > 0


def test_context_is_cached() -> None:
    assert ssl_config.create_verified_ssl_context() is ssl_config.create_verified_ssl_context()


def test_verify_option_maps_bool_to_context_or_false() -> None:
    assert isinstance(ssl_config.verify_option(True), ssl.SSLContext)
    assert ssl_config.verify_option(False) is False


def test_context_accepted_by_httpx_client() -> None:
    # Guards the "httpx accepts an ssl.SSLContext for verify=" assumption.
    with httpx.Client(verify=ssl_config.create_verified_ssl_context()) as client:
        assert client is not None


def test_missing_certifi_bundle_falls_back_to_os_store(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(ssl_config.certifi, "where", lambda: "/nonexistent/cacert.pem")

    context = ssl_config.create_verified_ssl_context()  # must not raise

    assert isinstance(context, ssl.SSLContext)
    assert "certifi bundle not loadable" in caplog.text

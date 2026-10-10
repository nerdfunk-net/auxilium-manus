"""Outbound-URL policy for a user-configured OpenAI-compatible endpoint (Ollama, LM Studio, ...).

Reuses ``core.safe_urls`` (http/https only, no embedded credentials, no link-local or metadata
targets, loopback only when ``ALLOW_LOOPBACK_SOURCE_URLS`` is set, every resolved address
checked). Checked when the URL is saved *and* again right before every call.
"""

from __future__ import annotations

from urllib.parse import urlparse

from core.config import settings
from core.safe_urls import (
    UnsafeURLError,
    validate_outbound_http_url,
    validate_outbound_http_url_async,
)

MAX_BASE_URL_CHARS = 512


class BaseUrlPolicyError(ValueError):
    """The configured URL is not allowed; the message is safe to show the user."""


def _check_transport(url: str, *, has_api_key: bool) -> None:
    # Outside development an API key must not travel over plain http. Without a key (typical for
    # a local model server on a trusted LAN) http is fine.
    if (
        has_api_key
        and settings.environment != "development"
        and urlparse(url).scheme.lower() != "https"
    ):
        raise BaseUrlPolicyError("An API key may only be sent to an https URL outside development")


def validate_llm_base_url(url: str, *, has_api_key: bool) -> str:
    """Normalised URL (no trailing slash) or ``BaseUrlPolicyError``. Resolves DNS (blocking)."""
    if len(url) > MAX_BASE_URL_CHARS:
        raise BaseUrlPolicyError("The URL is too long")
    try:
        safe = validate_outbound_http_url(url)
    except UnsafeURLError as exc:
        raise BaseUrlPolicyError(str(exc)) from exc
    _check_transport(safe, has_api_key=has_api_key)
    return safe


async def validate_llm_base_url_async(url: str, *, has_api_key: bool) -> str:
    """Same check off the event loop; used right before each provider call."""
    try:
        safe = await validate_outbound_http_url_async(url)
    except UnsafeURLError as exc:
        raise BaseUrlPolicyError(str(exc)) from exc
    _check_transport(safe, has_api_key=has_api_key)
    return safe

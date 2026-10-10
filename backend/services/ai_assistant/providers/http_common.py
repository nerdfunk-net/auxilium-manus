"""Shared plumbing for the httpx-based adapters (Gemini, OpenAI-compatible)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from services.ai_assistant.providers.base import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderUnavailableError,
)

DEFAULT_TIMEOUT = httpx.Timeout(120.0, connect=10.0)
MAX_ERROR_BODY_CHARS = 2000


def new_client() -> httpx.AsyncClient:
    # Redirects are never followed: a user-configured endpoint must not be able to bounce the
    # request (and its API key) to an address the URL policy never checked.
    return httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=False)


def error_for_status(status: int, body: str = "") -> ProviderError:
    """Neutral error for an HTTP failure. The response body is inspected, never echoed."""
    if status in (401, 403):
        return ProviderAuthError("The provider rejected the API key")
    if status == 400 and ("API_KEY_INVALID" in body or "API key not valid" in body):
        return ProviderAuthError("The provider rejected the API key")
    if status == 404:
        return ProviderRequestError("Model or endpoint not found")
    if status == 429:
        return ProviderRateLimitError("The provider rate limit or quota was reached")
    if status >= 500:
        return ProviderUnavailableError("The provider is temporarily unavailable")
    if 300 <= status < 400:
        return ProviderRequestError("The endpoint redirected the request, which is not allowed")
    return ProviderRequestError("The provider rejected the request")


async def raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 300:
        return
    body = (await response.aread()).decode("utf-8", errors="replace")[:MAX_ERROR_BODY_CHARS]
    raise error_for_status(response.status_code, body)


async def sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """Payloads of ``data:`` lines (comments, event names and blank lines are skipped)."""
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            yield line[len("data:") :].lstrip()


def unavailable(_exc: httpx.HTTPError) -> ProviderUnavailableError:
    """Transport failure. Neither the URL nor the exception text is exposed."""
    return ProviderUnavailableError("Could not reach the provider")

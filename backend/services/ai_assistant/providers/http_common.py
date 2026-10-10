"""Shared plumbing for the httpx-based adapters (Gemini, OpenAI-compatible)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from services.ai_assistant.providers.base import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderUnavailableError,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(120.0, connect=10.0)
MAX_ERROR_BODY_CHARS = 2000

# Brief server-side failures (e.g. Gemini answering 503 while a model is overloaded) are retried
# before any output has been streamed, so a retry can never duplicate text. 429 (quota) is not
# retried: waiting seconds does not fix it.
RETRYABLE_STATUSES = frozenset({500, 502, 503, 504})
RETRY_DELAYS_SECONDS: tuple[float, ...] = (1.0, 2.0)


def new_client() -> httpx.AsyncClient:
    # Redirects are never followed: a user-configured endpoint must not be able to bounce the
    # request (and its API key) to an address the URL policy never checked.
    return httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=False)


# A machine-readable error category such as RESOURCE_EXHAUSTED or invalid_request_error: short,
# token-like, and never free text, so it is safe to show and cannot carry request content.
_ERROR_CATEGORY = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{2,48}")


def _error_category(body: str) -> str | None:
    """The provider's own error category (``error.status`` / ``error.type`` / ``error.code``)."""
    try:
        error = (json.loads(body) or {}).get("error")
    except ValueError, AttributeError:
        return None
    if not isinstance(error, dict):
        return None
    for key in ("status", "type", "code"):
        value = error.get(key)
        if isinstance(value, str) and _ERROR_CATEGORY.fullmatch(value):
            return value
    return None


def error_for_status(status: int, body: str = "") -> ProviderError:
    """Neutral error for an HTTP failure.

    The body is inspected, never echoed: the message carries only the HTTP status and, when the
    provider names one, its short error category (for example ``HTTP 404 NOT_FOUND``), which is
    enough to tell a missing model from a quota problem.
    """
    category = _error_category(body)
    detail = f" (HTTP {status}{f' {category}' if category else ''})"
    if status in (401, 403):
        return ProviderAuthError(f"The provider rejected the API key or its permissions{detail}")
    if status == 400 and ("API_KEY_INVALID" in body or "API key not valid" in body):
        return ProviderAuthError(f"The provider rejected the API key{detail}")
    if status == 404:
        return ProviderRequestError(
            f"Model or endpoint not found; the model may not be available to this key{detail}"
        )
    if status == 429:
        return ProviderRateLimitError(
            f"The provider rate limit or quota was reached; a free tier may not include this "
            f"model{detail}"
        )
    if status >= 500:
        return ProviderUnavailableError(f"The provider is temporarily unavailable{detail}")
    if 300 <= status < 400:
        return ProviderRequestError(
            f"The endpoint redirected the request, which is not allowed{detail}"
        )
    return ProviderRequestError(f"The provider rejected the request{detail}")


@asynccontextmanager
async def open_stream(
    client: httpx.AsyncClient,
    url: str,
    *,
    json_body: dict[str, Any],
    headers: dict[str, str],
    params: dict[str, str] | None = None,
) -> AsyncIterator[httpx.Response]:
    """POST and yield a streaming response, retrying transient failures *before* it starts.

    Errors raised while the caller consumes the stream are never retried here (output may
    already have been sent to the user).
    """
    request = client.build_request("POST", url, json=json_body, headers=headers, params=params)
    response: httpx.Response | None = None
    for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
        has_retry_left = attempt < len(RETRY_DELAYS_SECONDS)
        try:
            response = await client.send(request, stream=True)
        except httpx.TransportError:
            if not has_retry_left:
                raise
            logger.info("Provider connection failed; retrying")
        else:
            if response.status_code not in RETRYABLE_STATUSES or not has_retry_left:
                break
            logger.info("Provider answered HTTP %s; retrying", response.status_code)
            await response.aclose()
        await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt])
    if response is None:  # unreachable: the loop either breaks with a response or raises
        raise ProviderUnavailableError("Could not reach the provider")
    try:
        await raise_for_status(response)
        yield response
    finally:
        await response.aclose()


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

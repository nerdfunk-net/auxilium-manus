"""Cisco Catalyst Center Intent API client.

App-scoped httpx pools (TLS-verifying and non-verifying, because ``verify_ssl`` is a
per-source setting); credentials arrive per call. Authentication is the Catalyst Center
token flow: ``POST /dna/system/api/v1/auth/token`` with HTTP Basic returns a token that is
sent as ``X-Auth-Token``. Tokens are cached in memory per (url, user, password digest) and
refreshed once on a 401.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from core.safe_urls import UnsafeURLError, validate_source_transport_async
from core.ssl_config import create_verified_ssl_context, verify_option
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterAuthError,
    CatalystCenterNotFoundError,
    CatalystCenterRateLimitError,
    CatalystCenterValidationError,
)
from services.catalyst_center.credentials import CatalystCenterCredentials

logger = logging.getLogger(__name__)

AUTH_PATH = "/dna/system/api/v1/auth/token"
RELEASE_PATH = "/dna/intent/api/v1/dnac-release"

# Catalyst Center tokens live 60 minutes by default; refresh early to stay clear of expiry.
_TOKEN_TTL_SECONDS = 50 * 60
_MAX_ERROR_MESSAGE_CHARS = 300
# Catalyst Center throttles bursts with HTTP 429: wait (Retry-After, else exponential
# 1s/2s/4s backoff, capped) and retry a bounded number of times before giving up.
_MAX_RATE_LIMIT_RETRIES = 3
_MAX_RETRY_WAIT_SECONDS = 30.0

_TokenKey = tuple[str, str, str]


class CatalystCenterService:
    """Async Cisco Catalyst Center client (token auth, typed errors)."""

    def __init__(self) -> None:
        self._client_verify: httpx.AsyncClient | None = None
        self._client_no_verify: httpx.AsyncClient | None = None
        self._tokens: dict[_TokenKey, tuple[str, float]] = {}
        self._token_lock = asyncio.Lock()
        self._sleep = asyncio.sleep  # replaced in tests

    async def startup(self) -> None:
        self._client_verify = httpx.AsyncClient(verify=create_verified_ssl_context())
        # verify=False is an opt-in per-source setting (verify_ssl); see doc/SECURITY-NOTES.md
        self._client_no_verify = httpx.AsyncClient(verify=False)  # noqa: S501
        logger.info("CatalystCenterService started")

    async def shutdown(self) -> None:
        if self._client_verify is not None:
            await self._client_verify.aclose()
            self._client_verify = None
        if self._client_no_verify is not None:
            await self._client_no_verify.aclose()
            self._client_no_verify = None
        self._tokens.clear()
        logger.info("CatalystCenterService shut down")

    async def request(
        self,
        credentials: CatalystCenterCredentials,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Call an Intent API path and return the decoded JSON body (``{}`` if empty)."""
        base = await self._validated_base(credentials)
        url = f"{base}/{path.lstrip('/')}"
        for attempt in (0, 1):
            token = await self._token(credentials, base)
            response = await self._send(
                credentials,
                method,
                url,
                params=params,
                json=json,
                headers={"Accept": "application/json", "X-Auth-Token": token},
            )
            if response.status_code == 401 and attempt == 0:
                self._tokens.pop(self._token_key(credentials, base), None)
                continue
            return self._handle_response(response, path)
        raise CatalystCenterAPIError("Catalyst Center request failed")  # pragma: no cover

    async def _validated_base(self, credentials: CatalystCenterCredentials) -> str:
        if not credentials.base_url or not credentials.username or not credentials.password:
            raise CatalystCenterValidationError(
                "Catalyst Center base URL, username, and password are required"
            )
        try:
            base = await validate_source_transport_async(
                credentials.base_url, verify_ssl=credentials.verify_ssl
            )
        except UnsafeURLError as exc:
            raise CatalystCenterValidationError(str(exc)) from exc
        if not credentials.verify_ssl:
            logger.warning(
                "Catalyst Center request with verify_ssl=False url_host=%s",
                urlparse(base).hostname,
            )
        return base.rstrip("/")

    @staticmethod
    def _token_key(credentials: CatalystCenterCredentials, base: str) -> _TokenKey:
        digest = hashlib.sha256(credentials.password.encode()).hexdigest()
        return (base, credentials.username, digest)

    async def _token(self, credentials: CatalystCenterCredentials, base: str) -> str:
        key = self._token_key(credentials, base)
        cached = self._tokens.get(key)
        if cached is not None and cached[1] > time.monotonic():
            return cached[0]
        async with self._token_lock:
            cached = self._tokens.get(key)
            if cached is not None and cached[1] > time.monotonic():
                return cached[0]
            token = await self._fetch_token(credentials, base)
            self._tokens[key] = (token, time.monotonic() + _TOKEN_TTL_SECONDS)
            return token

    async def _fetch_token(self, credentials: CatalystCenterCredentials, base: str) -> str:
        response = await self._send(
            credentials,
            "POST",
            f"{base}{AUTH_PATH}",
            headers={"Accept": "application/json"},
            auth=(credentials.username, credentials.password),
        )
        if response.status_code in (401, 403):
            raise CatalystCenterAuthError("Catalyst Center rejected the credentials")
        if response.status_code != 200:
            raise CatalystCenterAPIError(
                f"Catalyst Center token request failed with status {response.status_code}"
            )
        try:
            token = response.json().get("Token")
        except (ValueError, AttributeError) as exc:
            raise CatalystCenterAPIError("Catalyst Center token response was not valid") from exc
        if not isinstance(token, str) or not token:
            raise CatalystCenterAPIError("Catalyst Center token response had no token")
        return token

    async def _send(
        self,
        credentials: CatalystCenterCredentials,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json: Any = None,
        auth: tuple[str, str] | None = None,
    ) -> httpx.Response:
        """Send one logical request, retrying HTTP 429 a bounded number of times."""
        for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
            response = await self._send_once(
                credentials, method, url, headers=headers, params=params, json=json, auth=auth
            )
            if response.status_code != 429:
                return response
            if attempt == _MAX_RATE_LIMIT_RETRIES:
                break
            wait = _retry_wait(response, attempt)
            logger.warning("Catalyst Center rate limited; retrying in %.1fs", wait)
            await self._sleep(wait)
        raise CatalystCenterRateLimitError("Catalyst Center rate limit exceeded; try again later")

    async def _send_once(
        self,
        credentials: CatalystCenterCredentials,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json: Any = None,
        auth: tuple[str, str] | None = None,
    ) -> httpx.Response:
        client = self._client_verify if credentials.verify_ssl else self._client_no_verify
        try:
            if client is not None:
                return await client.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=headers,
                    auth=auth,
                    timeout=credentials.timeout,
                )
            async with httpx.AsyncClient(verify=verify_option(credentials.verify_ssl)) as fallback:
                return await fallback.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=headers,
                    auth=auth,
                    timeout=credentials.timeout,
                )
        except httpx.TimeoutException as exc:
            raise CatalystCenterAPIError(
                f"Catalyst Center request timed out after {credentials.timeout} seconds"
            ) from exc
        except Exception as exc:
            logger.error("Catalyst Center request failed: %s", type(exc).__name__)
            raise CatalystCenterAPIError("Catalyst Center request failed") from exc

    def _handle_response(self, response: httpx.Response, path: str) -> Any:
        status = response.status_code
        if 200 <= status < 300:
            if not response.content:
                return {}
            try:
                return response.json()
            except ValueError as exc:
                raise CatalystCenterAPIError(
                    f"Catalyst Center returned a non-JSON body for {path}"
                ) from exc
        if status in (401, 403):
            raise CatalystCenterAuthError("Catalyst Center denied the request")
        if status == 404:
            raise CatalystCenterNotFoundError(f"Catalyst Center resource not found: {path}")
        if status == 400:
            raise CatalystCenterValidationError(self._error_message(response))
        raise CatalystCenterAPIError(
            f"Catalyst Center request failed with status {status} for {path}"
        )

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        fallback = "Catalyst Center rejected the request (400 Bad Request)"
        try:
            payload = response.json()
        except ValueError:
            return fallback
        body = payload.get("response") if isinstance(payload, dict) else None
        source = body if isinstance(body, dict) else payload
        message = source.get("message") if isinstance(source, dict) else None
        if isinstance(message, str) and message.strip():
            return message.strip()[:_MAX_ERROR_MESSAGE_CHARS]
        return fallback


def _retry_wait(response: httpx.Response, attempt: int) -> float:
    """Seconds to wait before retrying a 429: ``Retry-After`` if usable, else backoff."""
    try:
        requested = float(response.headers.get("Retry-After", ""))
    except ValueError:
        requested = math.nan
    if math.isfinite(requested) and requested >= 0:
        return min(requested, _MAX_RETRY_WAIT_SECONDS)
    return min(float(2**attempt), _MAX_RETRY_WAIT_SECONDS)

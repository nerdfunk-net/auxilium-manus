"""Nautobot GraphQL and REST client with per-request credentials."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from core.safe_urls import UnsafeURLError, validate_outbound_http_url
from services.nautobot.common.exceptions import (
    NautobotAPIError,
    NautobotNotFoundError,
    NautobotValidationError,
)
from services.nautobot.credentials import NautobotCredentials

logger = logging.getLogger(__name__)


class NautobotService:
    """Async Nautobot API client.

    Keeps two app-scoped ``httpx.AsyncClient`` pools (TLS-verifying and
    non-verifying) because ``verify_ssl`` is a per-source, per-request setting
    (some Nautobot lab/dev instances use self-signed certificates).
    """

    def __init__(self) -> None:
        self._client_verify: httpx.AsyncClient | None = None
        self._client_no_verify: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        self._client_verify = httpx.AsyncClient(verify=True)
        self._client_no_verify = httpx.AsyncClient(verify=False)
        logger.info("NautobotService started")

    async def shutdown(self) -> None:
        if self._client_verify is not None:
            await self._client_verify.aclose()
            self._client_verify = None
        if self._client_no_verify is not None:
            await self._client_no_verify.aclose()
            self._client_no_verify = None
        logger.info("NautobotService shut down")

    def _client_for(self, verify_ssl: bool) -> httpx.AsyncClient | None:
        return self._client_verify if verify_ssl else self._client_no_verify

    async def test_connection(self, credentials: NautobotCredentials) -> dict[str, Any]:
        """Verify URL + token with a lightweight authenticated REST call.

        Uses ``GET /api/status/`` — available on all Nautobot versions and
        requires a valid token (unless view permissions are globally exempted).

        Raises:
            NautobotValidationError: Missing credentials or unsafe URL.
            NautobotAPIError: Auth failure, network error, or non-2xx response.

        Returns:
            The parsed ``/api/status/`` JSON payload on success.
        """
        return await self.rest_request("status/", credentials)

    async def graphql_query(
        self,
        query: str,
        variables: dict[str, Any] | None,
        credentials: NautobotCredentials,
    ) -> dict[str, Any]:
        if not credentials.url or not credentials.token:
            raise NautobotValidationError("Nautobot URL and token are required")

        try:
            base = validate_outbound_http_url(credentials.url, resolve_dns=True)
        except UnsafeURLError as exc:
            raise NautobotValidationError(str(exc)) from exc

        graphql_url = f"{base}/api/graphql/"
        if not credentials.verify_ssl:
            logger.warning(
                "Nautobot GraphQL with verify_ssl=False url_host=%s",
                urlparse(base).hostname,
            )
        headers = {
            "Authorization": f"Token {credentials.token}",
            "Content-Type": "application/json",
        }
        payload = {"query": query, "variables": variables or {}}

        try:
            response = await self._do_post(
                graphql_url,
                payload,
                headers,
                credentials.timeout,
                credentials.verify_ssl,
            )
            if response.status_code == 200:
                return response.json()
            raise NautobotAPIError(
                f"GraphQL request failed with status {response.status_code}: {response.text}"
            )
        except httpx.TimeoutException as exc:
            raise NautobotAPIError(
                f"GraphQL request timed out after {credentials.timeout} seconds"
            ) from exc
        except NautobotAPIError:
            raise
        except Exception as exc:
            logger.error("GraphQL query failed: %s", exc)
            raise NautobotAPIError("GraphQL query failed") from exc

    async def rest_request(
        self,
        endpoint: str,
        credentials: NautobotCredentials,
        method: str = "GET",
        data: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]:
        if not credentials.url or not credentials.token:
            raise NautobotValidationError("Nautobot URL and token are required")

        try:
            base = validate_outbound_http_url(credentials.url, resolve_dns=True)
        except UnsafeURLError as exc:
            raise NautobotValidationError(str(exc)) from exc

        api_url = f"{base}/api/{endpoint.lstrip('/')}"
        if not credentials.verify_ssl:
            logger.warning(
                "Nautobot REST with verify_ssl=False url_host=%s",
                urlparse(base).hostname,
            )
        headers = {
            "Authorization": f"Token {credentials.token}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._do_request(
                method,
                api_url,
                data,
                headers,
                credentials.timeout,
                credentials.verify_ssl,
            )
            if response.status_code in (200, 201, 204):
                if response.status_code == 204:
                    return {"status": "success", "message": "Resource deleted successfully"}
                return response.json()
            if response.status_code == 404:
                raise NautobotNotFoundError(f"Resource not found: {endpoint} — {response.text}")
            raise NautobotAPIError(
                f"REST request failed with status {response.status_code}: {response.text}"
            )
        except httpx.TimeoutException as exc:
            raise NautobotAPIError(
                f"REST request timed out after {credentials.timeout} seconds"
            ) from exc
        except NautobotAPIError:
            raise
        except Exception as exc:
            logger.error("REST request failed: %s", exc)
            raise NautobotAPIError("REST request failed") from exc

    async def _do_post(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
        verify_ssl: bool,
    ) -> httpx.Response:
        client = self._client_for(verify_ssl)
        if client is not None:
            return await client.post(url, json=payload, headers=headers, timeout=timeout)
        async with httpx.AsyncClient(verify=verify_ssl) as fallback_client:
            return await fallback_client.post(url, json=payload, headers=headers, timeout=timeout)

    async def _do_request(
        self,
        method: str,
        url: str,
        data: dict[str, Any] | list[Any] | None,
        headers: dict[str, str],
        timeout: float,
        verify_ssl: bool,
    ) -> httpx.Response:
        client = self._client_for(verify_ssl)
        if client is not None:
            return await client.request(method, url, json=data, headers=headers, timeout=timeout)
        async with httpx.AsyncClient(verify=verify_ssl) as fallback_client:
            return await fallback_client.request(
                method, url, json=data, headers=headers, timeout=timeout
            )

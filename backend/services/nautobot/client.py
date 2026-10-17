"""Nautobot GraphQL and REST client with per-request credentials."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from core.safe_urls import UnsafeURLError, validate_source_transport_async
from core.ssl_config import create_verified_ssl_context, verify_option
from services.nautobot.common.exceptions import (
    NautobotAPIError,
    NautobotNotFoundError,
    NautobotValidationError,
)
from services.nautobot.credentials import NautobotCredentials

logger = logging.getLogger(__name__)


def _log_error_body(kind: str, response: Any) -> None:
    """The response body never goes into an exception message (it reaches device errors and
    run results); its first 200 characters, tags stripped, go to the worker log only (C7-03)."""
    text = re.sub(r"<[^>]+>", " ", str(getattr(response, "text", "")))[:200]
    logger.error("Nautobot %s request failed status=%s body=%r", kind, response.status_code, text)


class NautobotService:
    """Async Nautobot API client.

    Keeps two app-scoped ``httpx.AsyncClient`` pools (TLS-verifying and
    non-verifying) because ``verify_ssl`` is a per-source, per-request setting
    (some Nautobot lab/dev instances use self-signed certificates). The verifying
    pool trusts the OS trust store (custom CAs installed via
    ``INSTALL_CERTIFICATE_FILES``) in addition to the ``certifi`` bundle.
    """

    def __init__(self) -> None:
        self._client_verify: httpx.AsyncClient | None = None
        self._client_no_verify: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        self._client_verify = httpx.AsyncClient(verify=create_verified_ssl_context())
        # verify=False is an opt-in per-source setting (verify_ssl); see doc/SECURITY-NOTES.md
        self._client_no_verify = httpx.AsyncClient(verify=False)  # noqa: S501
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
        *,
        strict: bool = False,
    ) -> dict[str, Any]:
        """Run a GraphQL query. With ``strict`` a response carrying ``errors`` raises
        (``code="graphql_error"``) instead of being returned for the caller to read ``data``
        from: partial data must never be taken for "no devices" (C3-05)."""
        if not credentials.url or not credentials.token:
            raise NautobotValidationError("Nautobot URL and token are required")

        try:
            base = await validate_source_transport_async(
                credentials.url, verify_ssl=credentials.verify_ssl
            )
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
                result = response.json()
                if strict and isinstance(result, dict) and result.get("errors"):
                    logger.error(
                        "Nautobot GraphQL answered with %d error(s); first: %.200s",
                        len(result["errors"]),
                        str(result["errors"][0]),
                    )
                    raise NautobotAPIError(
                        "Nautobot's GraphQL API reported an error for this query",
                        code="graphql_error",
                    )
                return result
            _log_error_body("GraphQL", response)
            raise NautobotAPIError(
                f"GraphQL request failed with status {response.status_code}",
                http_status=response.status_code,
            )
        except httpx.TimeoutException as exc:
            raise NautobotAPIError(
                f"GraphQL request timed out after {credentials.timeout} seconds", code="timeout"
            ) from exc
        except NautobotAPIError:
            raise
        except Exception as exc:
            logger.error("GraphQL query failed: %s", exc)
            raise NautobotAPIError("GraphQL query failed", code="transport") from exc

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
            base = await validate_source_transport_async(
                credentials.url, verify_ssl=credentials.verify_ssl
            )
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
                _log_error_body("REST", response)
                raise NautobotNotFoundError(f"Resource not found: {endpoint}", http_status=404)
            _log_error_body("REST", response)
            raise NautobotAPIError(
                f"REST request failed with status {response.status_code}",
                http_status=response.status_code,
            )
        except httpx.TimeoutException as exc:
            raise NautobotAPIError(
                f"REST request timed out after {credentials.timeout} seconds", code="timeout"
            ) from exc
        except NautobotAPIError:
            raise
        except Exception as exc:
            logger.error("REST request failed: %s", exc)
            raise NautobotAPIError("REST request failed", code="transport") from exc

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
        async with httpx.AsyncClient(verify=verify_option(verify_ssl)) as fallback_client:
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
        async with httpx.AsyncClient(verify=verify_option(verify_ssl)) as fallback_client:
            return await fallback_client.request(
                method, url, json=data, headers=headers, timeout=timeout
            )

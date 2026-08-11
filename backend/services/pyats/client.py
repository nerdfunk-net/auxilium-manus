"""pyATS shim HTTP client. App-scoped httpx clients; credentials per call."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from core.safe_urls import UnsafeURLError, validate_outbound_http_url
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from services.pyats.credentials import PyATSCredentials

logger = logging.getLogger(__name__)


class PyATSShimService:
    """Async client for the pyATS HTTP shim (health checks + job execution).

    Keeps two app-scoped ``httpx.AsyncClient`` pools (TLS-verifying and
    non-verifying) since ``verify_ssl`` is a per-source setting, mirroring
    ``services.ise.client.ISEService``.
    """

    def __init__(self) -> None:
        self._client_verify: httpx.AsyncClient | None = None
        self._client_no_verify: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        self._client_verify = httpx.AsyncClient(verify=True)
        self._client_no_verify = httpx.AsyncClient(verify=False)
        logger.info("PyATSShimService started")

    async def shutdown(self) -> None:
        if self._client_verify is not None:
            await self._client_verify.aclose()
            self._client_verify = None
        if self._client_no_verify is not None:
            await self._client_no_verify.aclose()
            self._client_no_verify = None
        logger.info("PyATSShimService shut down")

    async def check_health(self, credentials: PyATSCredentials) -> dict[str, Any]:
        return await self._get(f"{self._base_url(credentials)}/health", credentials)

    async def check_pyats_health(self, credentials: PyATSCredentials) -> dict[str, Any]:
        return await self._get(f"{self._base_url(credentials)}/health/pyats", credentials)

    async def run_job(
        self,
        credentials: PyATSCredentials,
        *,
        operation: str,
        devices: list[dict[str, Any]],
        commands: list[str],
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        base = self._base_url(credentials)
        body: dict[str, Any] = {"operation": operation, "devices": devices, "commands": commands}
        if timeout_seconds is not None:
            body["timeout_seconds"] = timeout_seconds
        request_timeout = timeout_seconds or credentials.timeout
        headers = {"Authorization": f"Bearer {credentials.token}"}

        try:
            response = await self._do_request(
                "POST", f"{base}/v1/jobs", credentials.verify_ssl, request_timeout,
                json=body, headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise PyATSAPIError(
                f"pyATS shim job request timed out after {request_timeout} seconds"
            ) from exc
        except PyATSAPIError:
            raise
        except Exception as exc:
            logger.error("pyATS shim job request failed: %s", exc)
            raise PyATSAPIError("pyATS shim job request failed") from exc

        if response.status_code == 400:
            raise PyATSValidationError(self._extract_error_message(response))
        if response.status_code >= 400:
            raise PyATSAPIError(f"pyATS shim job request failed with status {response.status_code}")
        return response.json()

    async def _get(self, url: str, credentials: PyATSCredentials) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {credentials.token}"} if credentials.token else {}
        try:
            response = await self._do_request(
                "GET", url, credentials.verify_ssl, credentials.timeout, headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise PyATSAPIError(
                f"pyATS shim request timed out after {credentials.timeout} seconds"
            ) from exc
        except Exception as exc:
            logger.error("pyATS shim health request failed: %s", exc)
            raise PyATSAPIError("pyATS shim health request failed") from exc

        if response.status_code >= 400:
            raise PyATSAPIError(f"pyATS shim request failed with status {response.status_code}")
        return response.json()

    def _base_url(self, credentials: PyATSCredentials) -> str:
        if not credentials.base_url:
            raise PyATSValidationError("pyATS shim URL is required")
        try:
            return validate_outbound_http_url(credentials.base_url, resolve_dns=True)
        except UnsafeURLError as exc:
            raise PyATSValidationError(str(exc)) from exc

    def _client_for(self, verify_ssl: bool) -> httpx.AsyncClient | None:
        return self._client_verify if verify_ssl else self._client_no_verify

    async def _do_request(
        self,
        method: str,
        url: str,
        verify_ssl: bool,
        timeout: float,
        **kwargs: Any,
    ) -> httpx.Response:
        client = self._client_for(verify_ssl)
        if client is not None:
            return await client.request(method, url, timeout=timeout, **kwargs)
        async with httpx.AsyncClient(verify=verify_ssl) as fallback_client:
            return await fallback_client.request(method, url, timeout=timeout, **kwargs)

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return "pyATS shim rejected the request (400 Bad Request)"
        detail = payload.get("detail")
        return str(detail) if detail else "pyATS shim rejected the request (400 Bad Request)"

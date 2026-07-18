"""Cisco ISE ERS API client. App-scoped httpx clients; credentials per call."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from services.ise.common.exceptions import (
    ISEAPIError,
    ISENotFoundError,
    ISEValidationError,
)
from services.ise.credentials import ISECredentials

logger = logging.getLogger(__name__)


class ISEService:
    """Async Cisco ISE ERS API client.

    Keeps two app-scoped ``httpx.AsyncClient`` pools (TLS-verifying and
    non-verifying) because ISE sandboxes commonly present self-signed
    certificates and ``verify_ssl`` is a per-source, per-request setting.
    """

    def __init__(self) -> None:
        self._client_verify: httpx.AsyncClient | None = None
        self._client_no_verify: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        self._client_verify = httpx.AsyncClient(verify=True)
        self._client_no_verify = httpx.AsyncClient(verify=False)
        logger.info("ISEService started")

    async def shutdown(self) -> None:
        if self._client_verify is not None:
            await self._client_verify.aclose()
            self._client_verify = None
        if self._client_no_verify is not None:
            await self._client_no_verify.aclose()
            self._client_no_verify = None
        logger.info("ISEService shut down")

    def _client_for(self, verify_ssl: bool) -> httpx.AsyncClient | None:
        return self._client_verify if verify_ssl else self._client_no_verify

    async def ers_request(
        self,
        endpoint: str,
        credentials: ISECredentials,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not credentials.base_url or not credentials.username or not credentials.password:
            raise ISEValidationError("ISE base URL, username, and password are required")

        url = f"{credentials.base_url.rstrip('/')}/ers/config/{endpoint.lstrip('/')}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        auth = (credentials.username, credentials.password)

        try:
            response = await self._do_request(
                method,
                url,
                data,
                params,
                headers,
                auth,
                credentials.timeout,
                credentials.verify_ssl,
            )
        except httpx.TimeoutException as exc:
            raise ISEAPIError(
                f"ISE request timed out after {credentials.timeout} seconds"
            ) from exc
        except ISEAPIError:
            raise
        except Exception as exc:
            logger.error("ISE ERS request failed: %s", exc)
            raise ISEAPIError("ISE ERS request failed") from exc

        return self._handle_response(response, endpoint)

    def _handle_response(self, response: httpx.Response, endpoint: str) -> dict[str, Any]:
        if response.status_code == 201:
            return {
                "id": self._id_from_location(response.headers.get("Location")),
                "location": response.headers.get("Location"),
            }
        if response.status_code == 200:
            return response.json() if response.content else {}
        if response.status_code == 204:
            return {"status": "success", "message": "Resource deleted successfully"}
        if response.status_code == 404:
            raise ISENotFoundError(f"ISE resource not found: {endpoint}")
        if response.status_code == 400:
            raise ISEValidationError(self._extract_error_message(response))
        raise ISEAPIError(
            f"ISE ERS request failed with status {response.status_code} for endpoint {endpoint}"
        )

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return "ISE rejected the request (400 Bad Request)"
        messages = (
            payload.get("ERSResponse", {})
            .get("messages", [])
        )
        texts = [m.get("title") for m in messages if isinstance(m, dict) and m.get("title")]
        return "; ".join(texts) if texts else "ISE rejected the request (400 Bad Request)"

    @staticmethod
    def _id_from_location(location: str | None) -> str | None:
        if not location:
            return None
        path = urlparse(location).path
        return path.rstrip("/").rsplit("/", 1)[-1] or None

    async def _do_request(
        self,
        method: str,
        url: str,
        data: dict[str, Any] | None,
        params: dict[str, Any] | None,
        headers: dict[str, str],
        auth: tuple[str, str],
        timeout: float,
        verify_ssl: bool,
    ) -> httpx.Response:
        client = self._client_for(verify_ssl)
        if client is not None:
            return await client.request(
                method,
                url,
                json=data,
                params=params,
                headers=headers,
                auth=auth,
                timeout=timeout,
            )
        async with httpx.AsyncClient(verify=verify_ssl) as fallback_client:
            return await fallback_client.request(
                method,
                url,
                json=data,
                params=params,
                headers=headers,
                auth=auth,
                timeout=timeout,
            )

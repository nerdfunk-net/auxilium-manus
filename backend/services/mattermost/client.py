"""Mattermost REST API client. App-scoped httpx clients; credentials per call."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from core.safe_urls import UnsafeURLError, validate_outbound_http_url_async
from core.ssl_config import create_verified_ssl_context, verify_option
from services.mattermost.common.exceptions import MattermostAPIError, MattermostValidationError
from services.mattermost.credentials import MattermostCredentials

logger = logging.getLogger(__name__)


class MattermostService:
    """Async client for the Mattermost REST API (v4).

    Keeps two app-scoped ``httpx.AsyncClient`` pools (TLS-verifying and
    non-verifying) since ``verify_ssl`` is a per-source setting, mirroring
    ``services.pyats.client.PyATSShimService``. The verifying pool trusts the OS
    trust store (custom CAs installed via ``INSTALL_CERTIFICATE_FILES``) in
    addition to the ``certifi`` bundle.
    """

    def __init__(self) -> None:
        self._client_verify: httpx.AsyncClient | None = None
        self._client_no_verify: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        self._client_verify = httpx.AsyncClient(verify=create_verified_ssl_context())
        # verify=False is an opt-in per-source setting (verify_ssl); see doc/SECURITY-NOTES.md
        self._client_no_verify = httpx.AsyncClient(verify=False)  # noqa: S501
        logger.info("MattermostService started")

    async def shutdown(self) -> None:
        if self._client_verify is not None:
            await self._client_verify.aclose()
            self._client_verify = None
        if self._client_no_verify is not None:
            await self._client_no_verify.aclose()
            self._client_no_verify = None
        logger.info("MattermostService shut down")

    async def check_connection(self, credentials: MattermostCredentials) -> dict[str, Any]:
        """Verify the token is valid and Mattermost is reachable.

        ``GET /api/v4/users/me`` doubles as both a reachability and an auth
        check: an invalid/expired token returns 401, an unreachable server
        raises a timeout/connection error, and success returns the
        authenticated (bot) user's profile.
        """
        base = await self._base_url(credentials)
        headers = {"Authorization": f"Bearer {credentials.token}"}
        try:
            response = await self._do_request(
                "GET",
                f"{base}/api/v4/users/me",
                credentials.verify_ssl,
                credentials.timeout,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise MattermostAPIError(
                f"Mattermost request timed out after {credentials.timeout} seconds"
            ) from exc
        except Exception as exc:
            logger.error("Mattermost connection check failed: %s", exc)
            raise MattermostAPIError("Mattermost connection check failed") from exc

        if response.status_code == 401:
            raise MattermostAPIError("Mattermost rejected the token (401 Unauthorized)")
        if response.is_redirect:
            location = response.headers.get("location", "")
            raise MattermostAPIError(
                f"Mattermost redirected the request (HTTP {response.status_code}"
                f"{f' to {location}' if location else ''}). Check that the source URL "
                "uses the scheme and hostname Mattermost expects (e.g. https)."
            )
        if response.status_code >= 400:
            raise MattermostAPIError(
                f"Mattermost request failed with status {response.status_code}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise MattermostAPIError(
                f"Mattermost returned a non-JSON response (HTTP {response.status_code})"
            ) from exc

    async def get_channel_by_name(
        self, credentials: MattermostCredentials, team_name: str, channel_name: str
    ) -> dict[str, Any]:
        """Resolve a channel to its id via team name + channel name.

        ``GET /api/v4/teams/name/{team_name}/channels/name/{channel_name}``.
        """
        base = await self._base_url(credentials)
        headers = {"Authorization": f"Bearer {credentials.token}"}
        try:
            response = await self._do_request(
                "GET",
                f"{base}/api/v4/teams/name/{team_name}/channels/name/{channel_name}",
                credentials.verify_ssl,
                credentials.timeout,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise MattermostAPIError(
                f"Mattermost request timed out after {credentials.timeout} seconds"
            ) from exc
        except Exception as exc:
            logger.error("Mattermost channel lookup failed: %s", exc)
            raise MattermostAPIError("Mattermost channel lookup failed") from exc

        if response.status_code == 401:
            raise MattermostAPIError("Mattermost rejected the token (401 Unauthorized)")
        if response.status_code == 404:
            raise MattermostAPIError(
                f"Mattermost channel '{channel_name}' not found in team '{team_name}'"
            )
        if response.is_redirect:
            location = response.headers.get("location", "")
            raise MattermostAPIError(
                f"Mattermost redirected the request (HTTP {response.status_code}"
                f"{f' to {location}' if location else ''}). Check that the source URL "
                "uses the scheme and hostname Mattermost expects (e.g. https)."
            )
        if response.status_code >= 400:
            raise MattermostAPIError(
                f"Mattermost request failed with status {response.status_code}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise MattermostAPIError(
                f"Mattermost returned a non-JSON response (HTTP {response.status_code})"
            ) from exc

    async def create_post(
        self, credentials: MattermostCredentials, channel_id: str, message: str
    ) -> dict[str, Any]:
        """Post a message to a channel. ``POST /api/v4/posts``."""
        base = await self._base_url(credentials)
        headers = {"Authorization": f"Bearer {credentials.token}"}
        try:
            response = await self._do_request(
                "POST",
                f"{base}/api/v4/posts",
                credentials.verify_ssl,
                credentials.timeout,
                headers=headers,
                json={"channel_id": channel_id, "message": message},
            )
        except httpx.TimeoutException as exc:
            raise MattermostAPIError(
                f"Mattermost request timed out after {credentials.timeout} seconds"
            ) from exc
        except Exception as exc:
            logger.error("Mattermost post failed: %s", exc)
            raise MattermostAPIError("Mattermost post failed") from exc

        if response.status_code == 401:
            raise MattermostAPIError("Mattermost rejected the token (401 Unauthorized)")
        if response.is_redirect:
            location = response.headers.get("location", "")
            raise MattermostAPIError(
                f"Mattermost redirected the request (HTTP {response.status_code}"
                f"{f' to {location}' if location else ''}). Check that the source URL "
                "uses the scheme and hostname Mattermost expects (e.g. https)."
            )
        if response.status_code >= 400:
            raise MattermostAPIError(
                f"Mattermost request failed with status {response.status_code}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise MattermostAPIError(
                f"Mattermost returned a non-JSON response (HTTP {response.status_code})"
            ) from exc

    async def _base_url(self, credentials: MattermostCredentials) -> str:
        if not credentials.base_url:
            raise MattermostValidationError("Mattermost URL is required")
        try:
            return await validate_outbound_http_url_async(credentials.base_url)
        except UnsafeURLError as exc:
            raise MattermostValidationError(str(exc)) from exc

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
        if not verify_ssl:
            logger.warning(
                "Mattermost request with verify_ssl=False url_host=%s",
                urlparse(url).hostname,
            )
        client = self._client_for(verify_ssl)
        if client is not None:
            return await client.request(method, url, timeout=timeout, **kwargs)
        async with httpx.AsyncClient(verify=verify_option(verify_ssl)) as fallback_client:
            return await fallback_client.request(method, url, timeout=timeout, **kwargs)

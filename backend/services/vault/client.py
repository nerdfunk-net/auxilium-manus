"""Synchronous OpenBao (Vault) KV v2 client.

Deliberately synchronous: the entire credential-resolution call graph
(``sqlalchemy`` ``Session``, FastAPI ``def`` endpoints, worker step code) is
synchronous, so a sync client avoids a sync<->async bridge inside
:class:`~services.credentials.credentials_service.CredentialsService`. The one
async part is the background token-renewal loop, driven from this service's
``startup``/``shutdown`` (the app lifespan and each Hatchet worker's
``start_all``). See ``doc/VAULT_INTEGRATION.md``.

Structure mirrors :class:`services.nautobot.client.NautobotService`
(``startup``/``shutdown`` + a pooled client with an ephemeral fallback).
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging

import httpx

from core.ssl_config import create_verified_ssl_context
from services.vault.auth import build_auth_strategy
from services.vault.cache import InProcessTTLCache
from services.vault.config import VaultConfig
from services.vault.exceptions import (
    VaultConflictError,
    VaultError,
    VaultPermissionError,
    VaultSecretNotFoundError,
    VaultUnavailableError,
)
from services.vault.token_manager import VaultTokenManager

logger = logging.getLogger(__name__)

RENEW_RETRY_AFTER_FAILURE_SECONDS = 60


class OpenBaoService:
    def __init__(self, cfg: VaultConfig) -> None:
        self._cfg = cfg
        self._client: httpx.Client | None = None
        self._tokens = VaultTokenManager(cfg, build_auth_strategy(cfg))
        self._cache = InProcessTTLCache(ttl_seconds=cfg.cache_ttl_seconds)
        self._renew_task: asyncio.Task | None = None
        self._healthy = False

    @property
    def healthy(self) -> bool:
        """True once a login (startup or renew) has succeeded and no renew has
        failed since. ``startup()`` soft-fails by design (the app must boot
        without OpenBao); callers that need a hard answer -- the Secret
        Manager adapter's ``ensure_started`` (SM1) -- read this instead."""
        return self._healthy

    # ------------------------------------------------------------------ lifecycle
    def _build_client(self) -> httpx.Client:
        if not self._cfg.verify_ssl:
            verify: object = False
        elif self._cfg.ca_cert:
            verify = self._cfg.ca_cert
        else:
            verify = create_verified_ssl_context()

        cert = None
        if self._cfg.auth_method == "cert" and self._cfg.client_cert:
            cert = (
                (self._cfg.client_cert, self._cfg.client_key)
                if self._cfg.client_key
                else self._cfg.client_cert
            )

        return httpx.Client(
            base_url=self._cfg.addr.rstrip("/"),
            verify=verify,
            cert=cert,
            timeout=self._cfg.timeout_seconds,
        )

    async def _run_blocking(self, fn, *args) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, functools.partial(fn, *args))

    async def startup(self) -> None:
        self._client = self._build_client()
        try:
            await self._run_blocking(self._tokens.ensure_token, self._client)
            self._healthy = True
            self._tokens.warn_if_lease_mismatch()
            logger.info(
                "OpenBaoService %s started (addr=%s mount=%s)",
                self._cfg.role_label,
                self._cfg.addr,
                self._cfg.mount,
            )
        except VaultError:
            self._healthy = False
            logger.error(
                "OpenBaoService %s login failed at startup; vault-backed credentials "
                "will fail closed until OpenBao recovers",
                self._cfg.role_label,
                exc_info=True,
            )
        self._renew_task = asyncio.create_task(self._renew_loop())

    async def shutdown(self) -> None:
        if self._renew_task is not None:
            self._renew_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._renew_task
            self._renew_task = None
        if self._client is not None:
            self._client.close()
            self._client = None
        logger.info("OpenBaoService %s shut down", self._cfg.role_label)

    async def _renew_loop(self) -> None:
        delay = self._tokens.renew_interval_seconds()
        while True:
            await asyncio.sleep(delay)
            if self._client is None:
                delay = RENEW_RETRY_AFTER_FAILURE_SECONDS
                continue
            try:
                await self._run_blocking(self._tokens.renew, self._client)
                self._healthy = True
                delay = self._tokens.renew_interval_seconds()
            except VaultError:
                self._healthy = False
                delay = RENEW_RETRY_AFTER_FAILURE_SECONDS
                logger.warning(
                    "OpenBaoService %s token renew failed; will re-login on next use",
                    self._cfg.role_label,
                    exc_info=True,
                )

    # ------------------------------------------------------------------- requests
    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        authed: bool = True,
        _retry_on_403: bool = True,
    ) -> httpx.Response:
        client = self._client
        if client is None:
            raise VaultUnavailableError(
                f"OpenBaoService {self._cfg.role_label} is not started"
            )

        headers: dict[str, str] = {}
        if self._cfg.namespace:
            headers["X-Vault-Namespace"] = self._cfg.namespace
        if authed:
            # No-op when a token is already held; re-logs-in if startup soft-failed
            # and OpenBao has since recovered. Raises VaultError -> fail closed.
            self._tokens.ensure_token(client)
            headers["X-Vault-Token"] = self._tokens.current()

        try:
            response = client.request(method, path, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise VaultUnavailableError(
                f"OpenBao request {method} {path} failed: {exc}"
            ) from exc

        if response.status_code in (200, 201, 204):
            return response
        if response.status_code == 403 and authed and _retry_on_403:
            # An expired or revoked token also answers 403, but so does a genuine
            # policy denial. Ask OpenBao whether the token is still good (V7): if it
            # is, this is a denial -- do not burn a login on it.
            if self._token_is_valid(client, headers):
                raise VaultPermissionError(
                    f"OpenBao denied {method} {path} (HTTP 403) for {self._cfg.role_label}"
                )
            # Expired/revoked: re-login once and retry transparently so a single
            # expiry never fails a caller (V4).
            self._tokens.invalidate()
            return self._request(method, path, json=json, authed=authed, _retry_on_403=False)
        if response.status_code == 403:
            # Second 403 with a fresh token: a genuine policy denial. Keep the
            # token — invalidating it again would only cause a login storm.
            raise VaultPermissionError(
                f"OpenBao denied {method} {path} (HTTP 403) for {self._cfg.role_label}"
            )
        if response.status_code == 404:
            raise VaultSecretNotFoundError(f"OpenBao path not found: {path}")
        if response.status_code >= 500:
            raise VaultUnavailableError(
                f"OpenBao {method} {path} returned HTTP {response.status_code}"
            )
        if response.status_code == 400 and "check-and-set" in response.text:
            raise VaultConflictError(f"OpenBao check-and-set conflict at {path}")
        raise VaultError(f"OpenBao {method} {path} returned HTTP {response.status_code}")

    @staticmethod
    def _token_is_valid(client: httpx.Client, headers: dict[str, str]) -> bool:
        try:
            response = client.get("/v1/auth/token/lookup-self", headers=headers)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    # --------------------------------------------------------------------- KV v2
    def read_kv(self, path: str, *, version: int | None = None) -> dict:
        """Read the KV v2 secret at *path*. A pinned ``version`` bypasses the
        cache entirely (the cache only ever holds "latest")."""
        if version is None:
            cached = self._cache.get(path)
            if cached is not None:
                return cached

        request_path = f"/v1/{self._cfg.mount}/data/{path}"
        if version is not None:
            request_path += f"?version={version}"
        response = self._request("GET", request_path)
        body = response.json()
        data = ((body or {}).get("data") or {}).get("data")
        if data is None:
            raise VaultSecretNotFoundError(f"OpenBao path holds no secret data: {path}")
        if version is None:
            self._cache.set(path, data)
        return dict(data)

    def write_kv(self, path: str, data: dict, *, cas: int | None = None) -> int | None:
        """Write a new version; return its version number when OpenBao reports it.

        ``cas`` makes the write conditional on the current version (0 = create only
        if absent); a mismatch raises ``VaultConflictError`` (V10).
        """
        body: dict = {"data": data}
        if cas is not None:
            body["options"] = {"cas": cas}
        response = self._request("POST", f"/v1/{self._cfg.mount}/data/{path}", json=body)
        self._cache.set(path, data)
        try:
            version = ((response.json() or {}).get("data") or {}).get("version")
        except ValueError:
            return None
        return version if isinstance(version, int) else None

    def read_kv_with_version(self, path: str) -> tuple[dict, int | None]:
        """Uncached read returning ``(data, version)`` for read-modify-write (V10)."""
        body = self._request("GET", f"/v1/{self._cfg.mount}/data/{path}").json() or {}
        envelope = body.get("data") or {}
        data = envelope.get("data")
        if data is None:
            raise VaultSecretNotFoundError(f"OpenBao path holds no secret data: {path}")
        version = (envelope.get("metadata") or {}).get("version")
        return dict(data), version if isinstance(version, int) else None

    def merge_kv(
        self, path: str, new_fields: dict, *, attempts: int = 2
    ) -> tuple[dict, int | None]:
        """Read-merge-write ``new_fields`` into the secret at *path* with check-and-set.

        Returns ``(merged, new_version)``. A lost race is re-read and retried once;
        a second loss raises ``VaultConflictError``. Never served from the TTL cache,
        so concurrent writers in other processes cannot be overwritten (V10 / SM6).
        """
        for attempt in range(attempts):
            try:
                current, version = self.read_kv_with_version(path)
            except VaultSecretNotFoundError:
                # No readable data. A never-written path takes cas=0; a soft-deleted /
                # destroyed one still has metadata and needs its current version (cas=0
                # would be rejected forever).
                current, version = {}, self._current_version_or_zero(path)
            merged = {**current, **new_fields}
            try:
                return merged, self.write_kv(path, merged, cas=version)
            except VaultConflictError:
                if attempt == attempts - 1:
                    raise
        raise VaultConflictError(path)  # unreachable; keeps the type checker honest

    def _current_version_or_zero(self, path: str) -> int:
        try:
            meta = self.metadata_kv(path)
        except VaultSecretNotFoundError:
            return 0
        version = meta.get("current_version")
        return version if isinstance(version, int) else 0

    def invalidate(self, path: str) -> None:
        """Forget a cached secret (used when another client in this process wrote it, V8)."""
        self._cache.invalidate(path)

    def destroy_kv_versions(self, path: str, versions: list[int]) -> None:
        """Permanently destroy specific versions (KV v2 ``destroy`` endpoint)."""
        if not versions:
            return
        self._request(
            "POST", f"/v1/{self._cfg.mount}/destroy/{path}", json={"versions": versions}
        )

    def delete_kv(self, path: str) -> None:
        """Permanently remove the secret **and every version** (KV v2 ``metadata``
        endpoint). A plain ``DELETE …/data/<path>`` would only soft-delete the
        latest version and leave the history readable (V3)."""
        self._request("DELETE", f"/v1/{self._cfg.mount}/metadata/{path}")
        self._cache.invalidate(path)

    def metadata_kv(self, path: str) -> dict:
        """Return the KV v2 metadata envelope for *path*, including its
        ``versions`` map (``{"<n>": {"created_time": ..., "destroyed": ...}}``).
        Used by callers that need version history (e.g. the Secret Manager
        integration's ``get_field_history``) rather than just the latest value.
        """
        response = self._request("GET", f"/v1/{self._cfg.mount}/metadata/{path}")
        body = response.json()
        data = (body or {}).get("data")
        if data is None:
            raise VaultSecretNotFoundError(f"OpenBao path holds no metadata: {path}")
        return dict(data)

    def health(self) -> dict:
        return self._request("GET", "/v1/sys/health", authed=False).json()

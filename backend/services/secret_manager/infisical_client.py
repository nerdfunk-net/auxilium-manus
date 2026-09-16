"""Infisical-backed ``SecretManagerClient`` adapter.

New client — Infisical has no prior integration in this codebase to reuse.
Verified against Infisical's docs during the design pass (see
doc/SECRET_MANAGER_INTEGRATION.md): Universal Auth login, and the v4
create/list secrets endpoints. Update/delete verbs are assumed to follow the
same resource shape (``PATCH``/``DELETE /api/v4/secrets/{secretName}``) but
were not exhaustively fetched — confirm against
https://infisical.com/docs/api-reference and adjust before relying on this in
production. **Version-pinned reads are a known open question**: Infisical
exposes a ``version`` query param and a ``/api/v1/secret-versions`` endpoint,
but Infisical/infisical#3263 (open upstream issue) reports version-pinned
reads sometimes silently return the latest version instead — do not build
the "retrieve the previous TACACS key" workflow on this without testing it
against the actual deployed Infisical instance first.

Path/field mapping: our ``path`` maps onto Infisical's ``secretPath`` (a
folder), and our ``field`` maps onto Infisical's ``secretKey`` (an individual
secret name) — so a path with several fields becomes several individual
Infisical secrets sharing one ``secretPath``. This is both the natural
mapping onto Infisical's own primitives *and* what keeps secrets
human-readable in Infisical's UI (the reason Infisical was chosen over a
single opaque JSON blob per path — see the design doc's "Open design
question" section).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import httpx

from core.ssl_config import create_verified_ssl_context
from services.secret_manager.client import SecretVersionInfo
from services.secret_manager.config import SecretManagerConnectionConfig
from services.secret_manager.exceptions import (
    SecretManagerAuthError,
    SecretManagerConfigError,
    SecretManagerPermissionError,
    SecretManagerUnavailableError,
)

logger = logging.getLogger(__name__)

_TOKEN_EXPIRY_BUFFER_SECONDS = 60


@dataclass
class _InfisicalToken:
    access_token: str
    expires_at: float  # time.monotonic() deadline


class _InfisicalTokenManager:
    """Lazy login / re-login on expiry — no background renew loop.

    A deliberate v1 simplification: Infisical's default Universal Auth
    access-token TTL is a generous 7200s, unlike OpenBao's periodic-token
    model that ``doc/VAULT_INTEGRATION.md`` already commits a background
    renew loop to. Revisit if Infisical connections are configured with a
    much shorter TTL in practice.
    """

    def __init__(self, client_id: str, client_secret: str, *, role_label: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._role_label = role_label
        self._lock = threading.Lock()
        self._token: _InfisicalToken | None = None

    def current(self, http: httpx.Client) -> str:
        with self._lock:
            if self._token is None or time.monotonic() >= self._token.expires_at:
                self._token = self._login(http)
            return self._token.access_token

    def invalidate(self) -> None:
        with self._lock:
            self._token = None

    def _login(self, http: httpx.Client) -> _InfisicalToken:
        if not self._client_id or not self._client_secret:
            raise SecretManagerConfigError(
                f"Infisical connection {self._role_label!r} needs both a client id "
                "and client secret"
            )
        try:
            response = http.post(
                "/api/v1/auth/universal-auth/login",
                data={"clientId": self._client_id, "clientSecret": self._client_secret},
            )
        except httpx.HTTPError as exc:
            raise SecretManagerUnavailableError(
                f"Infisical Universal Auth login failed: {exc}"
            ) from exc
        if response.status_code != 200:
            raise SecretManagerAuthError(
                f"Infisical Universal Auth login returned HTTP {response.status_code}"
            )
        body = response.json()
        access_token = body.get("accessToken")
        if not access_token:
            raise SecretManagerAuthError("Infisical login response had no accessToken")
        expires_in = int(body.get("expiresIn") or 0)
        deadline = time.monotonic() + max(0, expires_in - _TOKEN_EXPIRY_BUFFER_SECONDS)
        logger.info("Infisical %s: authenticated (expires_in=%ss)", self._role_label, expires_in)
        return _InfisicalToken(access_token=access_token, expires_at=deadline)


class InfisicalSecretManagerClient:
    """Field-granular ``SecretManagerClient`` adapter over Infisical's REST API."""

    def __init__(self, cfg: SecretManagerConnectionConfig) -> None:
        self._name = cfg.name
        site_url = str(cfg.backend_config.get("site_url") or "").strip()
        project_id = str(cfg.backend_config.get("project_id") or "").strip()
        environment = str(cfg.backend_config.get("environment") or "").strip()
        if not site_url or not project_id or not environment:
            raise SecretManagerConfigError(
                f"Infisical connection '{cfg.name}' needs 'site_url', 'project_id', "
                "and 'environment' in backend_config"
            )
        self._project_id = project_id
        self._environment = environment
        self._client = httpx.Client(
            base_url=site_url.rstrip("/"),
            verify=create_verified_ssl_context() if cfg.verify_ssl else False,
            timeout=10.0,
        )
        self._tokens = _InfisicalTokenManager(cfg.auth_id, cfg.auth_secret, role_label=cfg.name)

    async def ensure_started(self) -> None:
        # No background renew loop — see _InfisicalTokenManager docstring.
        # Nothing to await; kept so the registry can treat every adapter
        # uniformly (await ensure_started() once before first use).
        return None

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        _retry_on_401: bool = True,
    ) -> httpx.Response:
        token = self._tokens.current(self._client)
        try:
            response = self._client.request(
                method,
                path,
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            raise SecretManagerUnavailableError(
                f"Infisical request {method} {path} failed: {exc}"
            ) from exc

        if response.status_code in (200, 201, 204):
            return response
        if response.status_code in (401, 403) and _retry_on_401:
            self._tokens.invalidate()
            return self._request(method, path, params=params, json=json, _retry_on_401=False)
        if response.status_code in (401, 403):
            raise SecretManagerPermissionError(
                f"Infisical denied {method} {path} (HTTP {response.status_code})"
            )
        if response.status_code == 404:
            return response  # callers interpret 404 per-endpoint (missing vs. empty)
        if response.status_code >= 500:
            raise SecretManagerUnavailableError(
                f"Infisical {method} {path} returned HTTP {response.status_code}"
            )
        raise SecretManagerUnavailableError(
            f"Infisical {method} {path} returned HTTP {response.status_code}: {response.text}"
        )

    def get_field(self, path: str, field: str, *, version: int | None = None) -> str | None:
        params: dict[str, str] = {
            "projectId": self._project_id,
            "environment": self._environment,
            "secretPath": path,
        }
        if version is not None:
            logger.warning(
                "Infisical get_field version=%s requested for '%s/%s' — version-pinned "
                "reads are unverified against a live deployment, see "
                "doc/SECRET_MANAGER_INTEGRATION.md",
                version,
                path,
                field,
            )
            params["version"] = str(version)
        response = self._request("GET", f"/api/v4/secrets/{field}", params=params)
        if response.status_code == 404:
            return None
        body = response.json()
        secret = body.get("secret") or {}
        value = secret.get("secretValue")
        return str(value) if value is not None else None

    def set_field(self, path: str, field: str, value: str) -> int | None:
        exists = self.get_field(path, field) is not None
        body = {
            "projectId": self._project_id,
            "environment": self._environment,
            "secretPath": path,
            "secretValue": value,
        }
        method = "PATCH" if exists else "POST"
        response = self._request(method, f"/api/v4/secrets/{field}", json=body)
        try:
            secret = (response.json() or {}).get("secret") or {}
        except ValueError:
            return None
        version = secret.get("version")
        return int(version) if isinstance(version, int) else None

    def delete_field(self, path: str, field: str) -> None:
        body = {
            "projectId": self._project_id,
            "environment": self._environment,
            "secretPath": path,
        }
        self._request("DELETE", f"/api/v4/secrets/{field}", json=body)

    def get_field_history(self, path: str, field: str) -> list[SecretVersionInfo]:
        del path
        # Not implemented pending live verification of version-pinned reads
        # (Infisical/infisical#3263) — see module docstring and
        # doc/SECRET_MANAGER_INTEGRATION.md. Returning an empty list keeps
        # callers "previous secret not available" rather than pretending
        # unverified data is trustworthy.
        logger.warning(
            "Infisical get_field_history('%s') not implemented pending live verification "
            "of version history support (see doc/SECRET_MANAGER_INTEGRATION.md)",
            field,
        )
        return []

    async def shutdown(self) -> None:
        self._client.close()

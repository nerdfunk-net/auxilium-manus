"""Pluggable authentication strategies for OpenBao.

AppRole is the primary method. Cert (mTLS) is a first-class swappable
alternative — its selection and wiring are complete; the login body is a thin
implementation that can be hardened in a fast follow-up. Token is a
**development-only** convenience for the ``docker/openbao`` dev container's root
token and is refused outside ``ENV=development``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from core.config import settings
from services.vault.config import VaultConfig
from services.vault.exceptions import VaultAuthError, VaultConfigError, VaultUnavailableError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VaultToken:
    """The result of authenticating: a client token plus its lease shape."""

    client_token: str
    lease_duration: int = 0
    renewable: bool = False
    period: int | None = None


class VaultAuthStrategy(Protocol):
    def login(self, http: httpx.Client) -> VaultToken: ...


def _post_login(http: httpx.Client, path: str, payload: dict, *, method_label: str) -> VaultToken:
    try:
        response = http.post(path, json=payload)
    except httpx.HTTPError as exc:
        raise VaultUnavailableError(
            f"OpenBao {method_label} login request failed: {exc}"
        ) from exc
    if response.status_code != 200:
        raise VaultAuthError(
            f"OpenBao {method_label} login returned HTTP {response.status_code}"
        )
    auth = response.json().get("auth") or {}
    client_token = auth.get("client_token")
    if not client_token:
        raise VaultAuthError(f"OpenBao {method_label} login response had no client_token")
    return VaultToken(
        client_token=client_token,
        lease_duration=int(auth.get("lease_duration", 0)),
        renewable=bool(auth.get("renewable", False)),
        period=auth.get("token_period") or auth.get("period"),
    )


class AppRoleAuth:
    """``POST /v1/auth/approle/login`` with ``role_id`` + ``secret_id``."""

    def __init__(self, cfg: VaultConfig) -> None:
        self._cfg = cfg

    def login(self, http: httpx.Client) -> VaultToken:
        role_id = self._cfg.role_id
        secret_id = self._cfg.resolved_secret_id()
        if not role_id or not secret_id:
            raise VaultConfigError(
                f"OpenBao AppRole auth for {self._cfg.role_label} needs both a "
                "role id and a secret id"
            )
        return _post_login(
            http,
            "/v1/auth/approle/login",
            {"role_id": role_id, "secret_id": secret_id},
            method_label="AppRole",
        )


class CertAuth:
    """``POST /v1/auth/cert/login`` — identity is the TLS client certificate.

    The client certificate/key are already loaded into the ``httpx.Client``'s
    SSL context by :class:`~services.vault.client.OpenBaoService` when
    ``auth_method == "cert"``; this call just exchanges it for a token.
    """

    def __init__(self, cfg: VaultConfig) -> None:
        self._cfg = cfg

    def login(self, http: httpx.Client) -> VaultToken:
        if not self._cfg.client_cert or not self._cfg.client_key:
            raise VaultConfigError(
                f"OpenBao cert auth for {self._cfg.role_label} needs a client "
                "certificate and key"
            )
        return _post_login(http, "/v1/auth/cert/login", {}, method_label="cert")


class TokenAuth:
    """Use a static token directly. Development only."""

    def __init__(self, cfg: VaultConfig) -> None:
        self._cfg = cfg

    def login(self, http: httpx.Client) -> VaultToken:  # noqa: ARG002 - no network call
        if not self._cfg.token:
            raise VaultConfigError(
                f"OpenBao token auth for {self._cfg.role_label} needs a token"
            )
        return VaultToken(client_token=self._cfg.token, renewable=False)


def build_auth_strategy(cfg: VaultConfig) -> VaultAuthStrategy:
    if cfg.auth_method == "approle":
        return AppRoleAuth(cfg)
    if cfg.auth_method == "cert":
        return CertAuth(cfg)
    if cfg.auth_method == "token":
        if settings.environment != "development":
            raise VaultConfigError(
                "OpenBao token auth is only permitted when ENV=development"
            )
        return TokenAuth(cfg)
    raise VaultConfigError(f"Unknown OpenBao auth method: {cfg.auth_method!r}")

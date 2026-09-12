"""In-memory lifecycle for the OpenBao client token.

The token is held in memory only — never written to a file, the database, or
Redis — so a process restart always re-authenticates from scratch. A periodic
token (OpenBao role ``token_period``) has no max TTL: as long as ``renew`` runs
within each period the same token lives indefinitely. On expiry or revocation
(HTTP 403 on renew) the manager falls back to a full ``login``.
"""

from __future__ import annotations

import logging
import threading

import httpx

from services.vault.auth import VaultAuthStrategy, VaultToken
from services.vault.config import VaultConfig
from services.vault.exceptions import VaultAuthError, VaultUnavailableError

logger = logging.getLogger(__name__)

MIN_RENEW_INTERVAL_SECONDS = 30


class VaultTokenManager:
    def __init__(self, cfg: VaultConfig, strategy: VaultAuthStrategy) -> None:
        self._cfg = cfg
        self._strategy = strategy
        self._lock = threading.Lock()
        self._token: VaultToken | None = None

    def _namespace_headers(self) -> dict[str, str]:
        return {"X-Vault-Namespace": self._cfg.namespace} if self._cfg.namespace else {}

    def current(self) -> str:
        with self._lock:
            if self._token is None:
                raise VaultAuthError(
                    f"OpenBao {self._cfg.role_label}: no client token (not logged in)"
                )
            return self._token.client_token

    def snapshot(self) -> VaultToken | None:
        with self._lock:
            return self._token

    def renew_interval_seconds(self) -> int:
        """Seconds until the next renew, driven by the lease OpenBao actually
        granted (V4). Falls back to the configured period when no token is held
        or the token carries no lease (static dev token)."""
        configured = max(60, self._cfg.token_period_seconds - self._cfg.renew_buffer_seconds)
        token = self.snapshot()
        if token is None or token.lease_duration <= 0:
            return configured
        lease_based = token.lease_duration - self._cfg.renew_buffer_seconds
        if lease_based < MIN_RENEW_INTERVAL_SECONDS:
            lease_based = max(MIN_RENEW_INTERVAL_SECONDS, token.lease_duration // 2)
        return min(configured, lease_based)

    def warn_if_lease_mismatch(self) -> None:
        """Log once at startup when the role does not match the configured cadence."""
        token = self.snapshot()
        if token is None or self._cfg.auth_method == "token":
            return
        if not token.renewable:
            logger.warning(
                "OpenBao %s: token is not renewable (lease=%ss); the client will re-login "
                "before each expiry. Configure the AppRole with token_period for a periodic token",
                self._cfg.role_label,
                token.lease_duration,
            )
        elif 0 < token.lease_duration < self._cfg.token_period_seconds:
            logger.warning(
                "OpenBao %s: granted lease %ss is shorter than VAULT_TOKEN_PERIOD_SECONDS=%s; "
                "renewing on the granted lease instead",
                self._cfg.role_label,
                token.lease_duration,
                self._cfg.token_period_seconds,
            )

    def ensure_token(self, http: httpx.Client) -> None:
        with self._lock:
            if self._token is None:
                self._token = self._strategy.login(http)
                logger.info(
                    "OpenBao %s: authenticated (renewable=%s, period=%s)",
                    self._cfg.role_label,
                    self._token.renewable,
                    self._token.period,
                )

    def invalidate(self) -> None:
        with self._lock:
            self._token = None

    def renew(self, http: httpx.Client) -> None:
        with self._lock:
            if self._token is None:
                self._token = self._strategy.login(http)
                return
            if not self._token.renewable:
                if self._token.lease_duration > 0:
                    # Leased but non-renewable (role without token_period): re-login
                    # proactively instead of letting it expire mid-request.
                    self._token = self._strategy.login(http)
                # Static/dev token (lease 0) — nothing to do.
                return
            try:
                response = http.post(
                    "/v1/auth/token/renew-self",
                    json={},
                    headers={
                        "X-Vault-Token": self._token.client_token,
                        **self._namespace_headers(),
                    },
                )
            except httpx.HTTPError as exc:
                raise VaultUnavailableError(
                    f"OpenBao {self._cfg.role_label} token renew request failed: {exc}"
                ) from exc

            if response.status_code == 200:
                auth = response.json().get("auth") or {}
                token = auth.get("client_token") or self._token.client_token
                self._token = VaultToken(
                    client_token=token,
                    lease_duration=int(auth.get("lease_duration", 0)),
                    renewable=bool(auth.get("renewable", True)),
                    period=auth.get("token_period") or auth.get("period") or self._token.period,
                )
                return

            # Expired / revoked / denied — drop and re-login.
            logger.warning(
                "OpenBao %s token renew returned HTTP %s; re-authenticating",
                self._cfg.role_label,
                response.status_code,
            )
            self._token = self._strategy.login(http)

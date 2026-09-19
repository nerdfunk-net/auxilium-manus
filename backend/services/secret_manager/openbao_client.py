"""OpenBao-backed ``SecretManagerClient`` adapter.

Reuses ``services.vault.client.OpenBaoService`` directly — that client is
already fully general KV v2 (mount + addr come from its ``VaultConfig``), so
no new KV wire-protocol code is needed, only a thin field-granular adapter
over its whole-dict-at-path methods and a ``VaultConfig`` built from a
``SecretManagerConnectionConfig`` instead of environment variables.
"""

from __future__ import annotations

import logging

from services.secret_manager.client import SecretVersionInfo
from services.secret_manager.config import SecretManagerConnectionConfig
from services.secret_manager.exceptions import (
    SecretManagerAuthError,
    SecretManagerConfigError,
    SecretManagerUnavailableError,
)
from services.secret_manager.transport_policy import validate_connection_transport
from services.vault.client import OpenBaoService
from services.vault.config import VaultConfig
from services.vault.exceptions import VaultError, VaultSecretNotFoundError

logger = logging.getLogger(__name__)


def _build_vault_config(cfg: SecretManagerConnectionConfig) -> VaultConfig:
    mount = str(cfg.backend_config.get("mount") or "").strip()
    try:
        # Rows can predate the CRUD-time check; re-validate without DNS (SM2).
        addr = validate_connection_transport(
            backend="openbao",
            backend_config=cfg.backend_config,
            verify_ssl=cfg.verify_ssl,
            resolve_dns=False,
        )
    except ValueError as exc:
        raise SecretManagerConfigError(f"OpenBao connection '{cfg.name}': {exc}") from exc
    if not mount:
        raise SecretManagerConfigError(
            f"OpenBao connection '{cfg.name}' needs 'mount' in backend_config"
        )
    if not cfg.auth_id or not cfg.auth_secret:
        raise SecretManagerConfigError(
            f"OpenBao connection '{cfg.name}' has no AppRole role_id/secret_id configured "
            "(set credential_name to a 'generic' credential holding them)"
        )
    return VaultConfig(
        addr=addr,
        mount=mount,
        namespace=str(cfg.backend_config.get("namespace") or ""),
        auth_method="approle",
        role_id=cfg.auth_id,
        secret_id=cfg.auth_secret,
        verify_ssl=cfg.verify_ssl,
        role_label=f"secret-manager:{cfg.name}",
    )


class OpenBaoSecretManagerClient:
    """Field-granular ``SecretManagerClient`` adapter over ``OpenBaoService``."""

    def __init__(self, cfg: SecretManagerConnectionConfig) -> None:
        self._name = cfg.name
        self._service = OpenBaoService(_build_vault_config(cfg))

    async def ensure_started(self) -> None:
        """Start the underlying client and *prove* the AppRole login worked.

        ``OpenBaoService.startup()`` deliberately swallows a failed login
        (the credential vault must not take the app down at boot); for a
        Secret Manager connection that would make ``POST …/test`` report
        success on a wrong secret_id (SM1). Shut the service down again on
        failure so its renew task does not leak, then raise.
        """
        await self._service.startup()
        if not self._service.healthy:
            await self._service.shutdown()
            raise SecretManagerAuthError(
                f"OpenBao connection '{self._name}': AppRole login failed -- check addr, "
                "mount, namespace, and the credential's role_id/secret_id"
            )

    def get_field(self, path: str, field: str, *, version: int | None = None) -> str | None:
        try:
            data = self._service.read_kv(path, version=version)
        except VaultSecretNotFoundError:
            return None
        except VaultError as exc:
            raise SecretManagerUnavailableError(str(exc)) from exc
        value = data.get(field)
        return str(value) if value is not None else None

    def set_field(self, path: str, field: str, value: str) -> int | None:
        try:
            current = self._service.read_kv(path)
        except VaultSecretNotFoundError:
            current = {}
        except VaultError as exc:
            raise SecretManagerUnavailableError(str(exc)) from exc
        merged = {**current, field: value}
        try:
            return self._service.write_kv(path, merged)
        except VaultError as exc:
            raise SecretManagerUnavailableError(str(exc)) from exc

    def delete_field(self, path: str, field: str) -> None:
        try:
            current = self._service.read_kv(path)
        except VaultSecretNotFoundError:
            return
        except VaultError as exc:
            raise SecretManagerUnavailableError(str(exc)) from exc
        if field not in current:
            return
        remaining = {key: val for key, val in current.items() if key != field}
        try:
            if remaining:
                self._service.write_kv(path, remaining)
            else:
                self._service.delete_kv(path)
        except VaultError as exc:
            raise SecretManagerUnavailableError(str(exc)) from exc

    def get_field_history(self, path: str, field: str) -> list[SecretVersionInfo]:
        del field  # OpenBao KV v2 versions the whole dict at `path`, not per field.
        try:
            metadata = self._service.metadata_kv(path)
        except VaultSecretNotFoundError:
            return []
        except VaultError as exc:
            raise SecretManagerUnavailableError(str(exc)) from exc
        versions = metadata.get("versions") or {}
        history = [
            SecretVersionInfo(version=int(number), created_at=str(info.get("created_time", "")))
            for number, info in versions.items()
            if not info.get("destroyed")
        ]
        return sorted(history, key=lambda item: item.version, reverse=True)

    async def shutdown(self) -> None:
        await self._service.shutdown()

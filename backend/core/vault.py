"""OpenBao (Vault) enablement flags and config builders.

Mirrors :mod:`core.dev_tools`: a thin, import-safe module that turns validated
:class:`core.config.Settings` fields into :class:`~services.vault.config.VaultConfig`
instances. Two roles: a read-only *runtime* config and a write-capable
*management* config. Management is mandatory whenever vault is enabled (single
mode — see ``doc/VAULT_INTEGRATION.md``).
"""

from __future__ import annotations

from core.config import settings
from services.vault.config import VaultConfig
from services.vault.exceptions import VaultConfigError


def vault_enabled() -> bool:
    return settings.vault_enabled


def vault_management_enabled() -> bool:
    # Single mode: if vault is on, the write-capable management role is required.
    return settings.vault_enabled


def _common_kwargs() -> dict:
    return {
        "addr": settings.vault_addr,
        "mount": settings.vault_kv_mount,
        "namespace": settings.vault_namespace,
        "auth_method": settings.vault_auth_method,
        "client_cert": settings.vault_client_cert,
        "client_key": settings.vault_client_key,
        "ca_cert": settings.vault_ca_cert,
        "verify_ssl": settings.vault_verify_ssl,
        "token_period_seconds": settings.vault_token_period_seconds,
        "renew_buffer_seconds": settings.vault_renew_buffer_seconds,
        "timeout_seconds": settings.vault_timeout_seconds,
        "cache_ttl_seconds": settings.vault_cache_ttl_seconds,
    }


def build_vault_config() -> VaultConfig:
    """Read-only runtime config (OpenBao policy ``manus-app``)."""
    return VaultConfig(
        **_common_kwargs(),
        role_id=settings.vault_role_id,
        secret_id=settings.vault_secret_id,
        secret_id_file=settings.vault_secret_id_file,
        token=settings.vault_token,
        role_label="manus-app",
    )


def build_vault_management_config() -> VaultConfig:
    """Write-capable management config (OpenBao policy ``manus-manage``)."""
    if settings.vault_auth_method == "token" and settings.environment != "development":
        raise VaultConfigError("OpenBao token auth is only permitted when ENV=development")
    return VaultConfig(
        **_common_kwargs(),
        role_id=settings.vault_manage_role_id,
        secret_id=settings.vault_manage_secret_id,
        secret_id_file=settings.vault_manage_secret_id_file,
        token=settings.vault_manage_token,
        role_label="manus-manage",
    )


def require_vault_management() -> None:
    if not vault_management_enabled():
        raise VaultConfigError("Vault management is not configured on this deployment")


async def start_vault_services() -> None:
    """Start the runtime + management OpenBao clients and register them as
    ``service_factory`` singletons. No-op unless ``VAULT_ENABLED``.

    Called from both the FastAPI lifespan and every Hatchet worker's
    ``start_all`` — the two lifespans that wire app-scoped services.
    """
    if not settings.vault_enabled:
        return

    import service_factory
    from services.vault.client import OpenBaoService

    runtime = OpenBaoService(build_vault_config())
    await runtime.startup()
    service_factory.set_vault_service(runtime)

    management = OpenBaoService(build_vault_management_config())
    await management.startup()
    service_factory.set_vault_management_service(management)


async def stop_vault_services() -> None:
    import service_factory

    runtime = service_factory.get_vault_service()
    if runtime is not None:
        await runtime.shutdown()
        service_factory.set_vault_service(None)

    management = service_factory.get_vault_management_service()
    if management is not None:
        await management.shutdown()
        service_factory.set_vault_management_service(None)

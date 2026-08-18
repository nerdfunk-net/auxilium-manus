"""FastAPI dependency providers."""

from __future__ import annotations

from fastapi import Depends, Query
from sqlalchemy.orm import Session

import service_factory
from core.database import get_db
from models.sources_nautobot import NautobotSourceRef
from services.auth.login_rate_limiter import LoginRateLimiter
from services.ise.source_config_service import ISESourceConfigService
from services.mattermost.source_config_service import MattermostSourceConfigService
from services.nautobot.credentials import NautobotCredentials
from services.pyats.source_config_service import PyATSSourceConfigService
from services.settings.settings_service import SettingsService
from services.sources.nautobot.persistence_service import InventoryService


def get_inventory_service(
    db: Session = Depends(get_db),
) -> InventoryService:
    return service_factory.build_inventory_service(db)


def get_ise_source_config_service(
    db: Session = Depends(get_db),
) -> ISESourceConfigService:
    return service_factory.build_ise_source_config_service(db)


def get_pyats_source_config_service(
    db: Session = Depends(get_db),
) -> PyATSSourceConfigService:
    return service_factory.build_pyats_source_config_service(db)


def get_mattermost_source_config_service(
    db: Session = Depends(get_db),
) -> MattermostSourceConfigService:
    return service_factory.build_mattermost_source_config_service(db)


def _credentials_from_source_config(
    config: dict,
    timeout: float = 30.0,
) -> NautobotCredentials:
    return service_factory.credentials_from_connection(
        str(config.get("url") or ""),
        str(config.get("token") or ""),
        timeout,
        verify_ssl=config.get("verify_ssl", True),
    )


def nautobot_credentials_from_source_id(
    source_id: str = Query(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
) -> NautobotCredentials:
    config = SettingsService(db).get_source_config("nautobot", source_id)
    return _credentials_from_source_config(config)


def nautobot_credentials_from_source_ref(
    ref: NautobotSourceRef,
    db: Session,
) -> NautobotCredentials:
    config = SettingsService(db).get_source_config("nautobot", ref.source_id)
    return _credentials_from_source_config(config, ref.timeout)


def get_git_service():
    return service_factory.build_git_service()


def get_git_auth_service():
    return service_factory.build_git_auth_service()


def get_git_cache_service():
    return service_factory.build_git_cache_service()


def get_git_operations_service():
    return service_factory.build_git_operations_service()


def get_git_connection_service():
    return service_factory.build_git_connection_service()


def get_cache_service():
    return service_factory.build_cache_service()


def get_git_debug_service():
    return service_factory.build_git_debug_service()


def get_git_version_control_service():
    return service_factory.build_git_version_control_service()


def get_git_file_service():
    return service_factory.build_git_file_service()


def get_git_csv_service():
    return service_factory.build_git_csv_service()


def get_oidc_config_service():
    return service_factory.build_oidc_config_service()


def get_oidc_service():
    return service_factory.build_oidc_service()


def get_login_rate_limiter() -> LoginRateLimiter:
    return service_factory.build_login_rate_limiter()

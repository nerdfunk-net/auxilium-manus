"""Service factory for constructing application services."""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.config import settings
from repositories.inventory_repository import InventoryRepository
from services.cache.redis_cache_service import RedisCacheService
from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials
from services.nautobot.metadata_service import NautobotMetadataService
from services.sources.nautobot.persistence_service import InventoryService
from services.sources.nautobot.source_service import NautobotSourceService

_cache_service: RedisCacheService | None = None
_nautobot_service: NautobotService | None = None


def get_nautobot_app_service() -> NautobotService:
    if _nautobot_service is None:
        raise RuntimeError("NautobotService is not initialized")
    return _nautobot_service


def set_nautobot_app_service(service: NautobotService) -> None:
    global _nautobot_service
    _nautobot_service = service


def build_cache_service() -> RedisCacheService | None:
    global _cache_service
    if _cache_service is not None:
        return _cache_service
    try:
        _cache_service = RedisCacheService(
            redis_url=settings.redis_url,
            key_prefix=settings.redis_key_prefix,
        )
        return _cache_service
    except Exception:
        return None


def credentials_from_connection(
    nautobot_url: str,
    nautobot_token: str,
    timeout: float = 30.0,
) -> NautobotCredentials:
    return NautobotCredentials(url=nautobot_url.rstrip("/"), token=nautobot_token, timeout=timeout)


def build_inventory_service(db: Session) -> InventoryService:
    return InventoryService(repository=InventoryRepository(db))


def build_nautobot_source_service(
    credentials: NautobotCredentials,
    db: Session | None = None,
) -> NautobotSourceService:
    persistence = build_inventory_service(db) if db is not None else None
    cache_svc = build_cache_service()
    device_ttl = 1800

    if db is not None and cache_svc is not None:
        from services.cache.cache_settings_service import CacheSettingsService

        cfg = CacheSettingsService(db, cache_svc).get_settings()
        if not cfg.enabled:
            cache_svc = None
        else:
            device_ttl = cfg.device_ttl_seconds

    return NautobotSourceService(
        nautobot=get_nautobot_app_service(),
        credentials=credentials,
        cache_service=cache_svc,
        persistence_service=persistence,
        device_ttl=device_ttl,
    )


def build_nautobot_metadata_service(
    credentials: NautobotCredentials,
) -> NautobotMetadataService:
    return NautobotMetadataService(get_nautobot_app_service(), credentials)


def build_git_service():
    from services.git.service import GitService

    return GitService()


def build_git_auth_service():
    from services.git.auth import GitAuthenticationService

    return GitAuthenticationService()


def build_git_cache_service():
    from services.git.cache import GitCacheService

    cache = build_cache_service()
    return GitCacheService(cache)


def build_git_repository_service():
    from services.git.repository_service import GitRepositoryService

    return GitRepositoryService()


def build_git_operations_service():
    from services.git.operations import GitOperationsService

    return GitOperationsService()


def build_git_connection_service():
    from services.git.connection import GitConnectionService

    return GitConnectionService()


def build_credentials_service(db: Session | None = None):
    from core.database import SessionLocal
    from services.credentials.credentials_service import CredentialsService

    session = db if db is not None else SessionLocal()
    return CredentialsService(session)


def build_git_debug_service():
    from services.git.debug_service import GitDebugService

    return GitDebugService()


def build_git_version_control_service():
    from services.git.version_control_service import GitVersionControlService

    return GitVersionControlService()

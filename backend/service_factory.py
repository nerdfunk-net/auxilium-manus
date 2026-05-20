"""Service factory for constructing application services."""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.config import settings
from repositories.inventory_repository import InventoryRepository
from services.cache.redis_cache_service import RedisCacheService
from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials
from services.nautobot.metadata_service import NautobotMetadataService
from services.sources.nautobot.persistence_service import InventoryPersistenceService
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


def build_inventory_persistence_service(db: Session) -> InventoryPersistenceService:
    return InventoryPersistenceService(repository=InventoryRepository(db))


def build_nautobot_source_service(
    credentials: NautobotCredentials,
    db: Session | None = None,
) -> NautobotSourceService:
    persistence = build_inventory_persistence_service(db) if db is not None else None
    return NautobotSourceService(
        nautobot=get_nautobot_app_service(),
        credentials=credentials,
        cache_service=build_cache_service(),
        persistence_service=persistence,
    )


def build_nautobot_metadata_service(
    credentials: NautobotCredentials,
) -> NautobotMetadataService:
    return NautobotMetadataService(get_nautobot_app_service(), credentials)

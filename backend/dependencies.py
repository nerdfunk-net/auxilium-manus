"""FastAPI dependency providers."""

from __future__ import annotations

from fastapi import Depends, Query
from sqlalchemy.orm import Session

import service_factory
from core.database import get_db
from models.sources_nautobot import NautobotConnection
from repositories.inventory_repository import InventoryRepository
from services.nautobot.credentials import NautobotCredentials
from services.sources.nautobot.persistence_service import InventoryPersistenceService


def get_inventory_persistence_service(
    db: Session = Depends(get_db),
) -> InventoryPersistenceService:
    return service_factory.build_inventory_persistence_service(db)


def nautobot_credentials_from_body(connection: NautobotConnection) -> NautobotCredentials:
    return service_factory.credentials_from_connection(
        connection.nautobot_url,
        connection.nautobot_token,
        connection.timeout,
    )


def nautobot_credentials_from_query(
    nautobot_url: str = Query(..., min_length=1),
    nautobot_token: str = Query(..., min_length=1),
) -> NautobotCredentials:
    return service_factory.credentials_from_connection(nautobot_url, nautobot_token)

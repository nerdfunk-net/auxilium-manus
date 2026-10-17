"""Router for database schema sync status/migration and RBAC re-seeding."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.dev_tools import require_dev_tools
from models.system import RbacSeedResponse, SchemaMigrationResponse, SchemaStatusResponse
from services.system.system_service import SystemService

router = APIRouter(
    prefix="/system",
    tags=["system"],
    dependencies=[Depends(get_current_user)],
)


def _service() -> SystemService:
    return SystemService()


@router.get(
    "/schema/status",
    response_model=SchemaStatusResponse,
    dependencies=[Depends(require_permission("system.database", "read"))],
)
def get_schema_status(service: SystemService = Depends(_service)) -> SchemaStatusResponse:
    return service.schema_status()


@router.post(
    "/schema/migrate",
    response_model=SchemaMigrationResponse,
    dependencies=[
        Depends(require_dev_tools),
        Depends(require_permission("system.database", "write")),
    ],
)
def migrate_schema(
    force: bool = False, service: SystemService = Depends(_service)
) -> SchemaMigrationResponse:
    return service.migrate_schema(force=force)


@router.post(
    "/rbac/seed",
    response_model=RbacSeedResponse,
    dependencies=[
        Depends(require_dev_tools),
        Depends(require_permission("system.rbac", "write")),
    ],
)
def reseed_rbac(
    remove_existing: bool = False,
    db: Session = Depends(get_db),
    service: SystemService = Depends(_service),
) -> RbacSeedResponse:
    return service.reseed_rbac(db, remove_existing=remove_existing)

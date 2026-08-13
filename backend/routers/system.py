"""Router for database schema sync status/migration and RBAC re-seeding."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.dev_tools import require_dev_tools
from core.schema_manager import SchemaManager
from models.system import RbacSeedResponse, SchemaMigrationResponse, SchemaStatusResponse
from services.auth.rbac_seed import admin_reseed_rbac

router = APIRouter(
    prefix="/system",
    tags=["system"],
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "/schema/status",
    response_model=SchemaStatusResponse,
    dependencies=[Depends(require_permission("system.database", "read"))],
)
async def get_schema_status() -> SchemaStatusResponse:
    return SchemaManager().get_schema_status()


@router.post(
    "/schema/migrate",
    response_model=SchemaMigrationResponse,
    dependencies=[
        Depends(require_dev_tools),
        Depends(require_permission("system.database", "write")),
    ],
)
async def migrate_schema(force: bool = False) -> SchemaMigrationResponse:
    return SchemaManager().perform_migration(force=force)


@router.post(
    "/rbac/seed",
    response_model=RbacSeedResponse,
    dependencies=[
        Depends(require_dev_tools),
        Depends(require_permission("system.rbac", "write")),
    ],
)
async def reseed_rbac(
    remove_existing: bool = False,
    db: Session = Depends(get_db),
) -> RbacSeedResponse:
    result = admin_reseed_rbac(db, remove_existing=remove_existing)
    return RbacSeedResponse(
        success=True,
        message=(
            "RBAC data wiped and re-seeded."
            if result.removed_existing
            else "RBAC catalog synchronized."
        ),
        permissions_seeded=result.permissions_seeded,
        roles_seeded=result.roles_seeded,
        removed_existing=result.removed_existing,
    )

"""Router for database schema sync status and on-demand migration."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core.auth import get_current_user, require_permission
from core.schema_manager import SchemaManager
from models.system import SchemaMigrationResponse, SchemaStatusResponse

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
    dependencies=[Depends(require_permission("system.database", "write"))],
)
async def migrate_schema(force: bool = False) -> SchemaMigrationResponse:
    return SchemaManager().perform_migration(force=force)

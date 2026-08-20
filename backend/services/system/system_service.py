"""System-level operations: schema status/migration and RBAC re-seeding."""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.schema_manager import SchemaManager
from models.system import RbacSeedResponse, SchemaMigrationResponse, SchemaStatusResponse
from services.auth.rbac_seed import admin_reseed_rbac


class SystemService:
    def schema_status(self) -> SchemaStatusResponse:
        return SchemaManager().get_schema_status()

    def migrate_schema(self, *, force: bool) -> SchemaMigrationResponse:
        return SchemaManager().perform_migration(force=force)

    def reseed_rbac(self, db: Session, *, remove_existing: bool) -> RbacSeedResponse:
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

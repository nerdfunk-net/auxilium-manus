from __future__ import annotations

from typing import Any

from sqlalchemy import text

from migrations.base import BaseMigration

CREATE_ROLES_TABLE = """
CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(500),
    is_system BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_roles_name UNIQUE (name)
)
"""

CREATE_PERMISSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS permissions (
    id SERIAL PRIMARY KEY,
    resource VARCHAR(100) NOT NULL,
    action VARCHAR(50) NOT NULL,
    description VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_permissions_resource_action UNIQUE (resource, action)
)
"""

CREATE_PERMISSIONS_RESOURCE_IDX = """
CREATE INDEX IF NOT EXISTS idx_permissions_resource ON permissions (resource)
"""

CREATE_ROLE_PERMISSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id INTEGER NOT NULL REFERENCES roles (id) ON DELETE CASCADE,
    permission_id INTEGER NOT NULL REFERENCES permissions (id) ON DELETE CASCADE,
    granted BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (role_id, permission_id)
)
"""

CREATE_USER_ROLES_TABLE = """
CREATE TABLE IF NOT EXISTS user_roles (
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES roles (id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id)
)
"""

CREATE_USER_PERMISSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS user_permissions (
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    permission_id INTEGER NOT NULL REFERENCES permissions (id) ON DELETE CASCADE,
    granted BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, permission_id)
)
"""


class Migration(BaseMigration):
    @property
    def name(self) -> str:
        return "012_create_rbac_tables"

    @property
    def description(self) -> str:
        return "Create RBAC tables: roles, permissions, role_permissions, user_roles, user_permissions"

    def upgrade(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(text(CREATE_ROLES_TABLE))
            conn.execute(text(CREATE_PERMISSIONS_TABLE))
            conn.execute(text(CREATE_PERMISSIONS_RESOURCE_IDX))
            conn.execute(text(CREATE_ROLE_PERMISSIONS_TABLE))
            conn.execute(text(CREATE_USER_ROLES_TABLE))
            conn.execute(text(CREATE_USER_PERMISSIONS_TABLE))
        return {
            "tables_created": [
                "roles",
                "permissions",
                "role_permissions",
                "user_roles",
                "user_permissions",
            ],
        }

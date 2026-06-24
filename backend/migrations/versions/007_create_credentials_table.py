from __future__ import annotations

from typing import Any

from sqlalchemy import text

from migrations.base import BaseMigration

CREATE_CREDENTIALS_TABLE = """
CREATE TABLE IF NOT EXISTS credentials (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    username VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL DEFAULT 'ssh',
    password_encrypted BYTEA,
    ssh_key_encrypted BYTEA,
    ssh_passphrase_encrypted BYTEA,
    valid_until VARCHAR(255),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    source VARCHAR(50) NOT NULL DEFAULT 'general',
    owner VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_credentials_name_source UNIQUE (name, source)
)
"""

CREATE_CREDENTIALS_SOURCE_IDX = """
CREATE INDEX IF NOT EXISTS idx_credentials_source ON credentials (source)
"""

CREATE_CREDENTIALS_OWNER_IDX = """
CREATE INDEX IF NOT EXISTS idx_credentials_owner ON credentials (owner)
"""


class Migration(BaseMigration):
    @property
    def name(self) -> str:
        return "007_create_credentials_table"

    @property
    def description(self) -> str:
        return "Create credentials table for encrypted SSH and device login storage"

    def upgrade(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(text(CREATE_CREDENTIALS_TABLE))
            conn.execute(text(CREATE_CREDENTIALS_SOURCE_IDX))
            conn.execute(text(CREATE_CREDENTIALS_OWNER_IDX))
        return {"tables_created": ["credentials"]}

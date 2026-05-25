from __future__ import annotations

from typing import Any

from sqlalchemy import text

from migrations.base import BaseMigration

CREATE_GIT_REPOSITORIES_TABLE = """
CREATE TABLE IF NOT EXISTS git_repositories (
    id                SERIAL PRIMARY KEY,
    name              VARCHAR(255) NOT NULL UNIQUE,
    category          VARCHAR(50)  NOT NULL,
    url               VARCHAR(1000) NOT NULL,
    branch            VARCHAR(255) NOT NULL DEFAULT 'main',
    auth_type         VARCHAR(50)  NOT NULL DEFAULT 'token',
    credential_name   VARCHAR(255),
    path              VARCHAR(1000),
    verify_ssl        BOOLEAN      NOT NULL DEFAULT TRUE,
    git_author_name   VARCHAR(255),
    git_author_email  VARCHAR(255),
    description       TEXT,
    is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
    last_sync         TIMESTAMP WITH TIME ZONE,
    sync_status       VARCHAR(255),
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
)
"""

CREATE_GIT_REPOSITORIES_NAME_IDX = """
CREATE INDEX IF NOT EXISTS ix_git_repositories_name
    ON git_repositories (name)
"""

CREATE_GIT_REPOSITORIES_CATEGORY_IDX = """
CREATE INDEX IF NOT EXISTS ix_git_repositories_category
    ON git_repositories (category)
"""


class Migration(BaseMigration):
    @property
    def name(self) -> str:
        return "006_add_git_repositories"

    @property
    def description(self) -> str:
        return "Create git_repositories table for managing Git repository configurations"

    def upgrade(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(text(CREATE_GIT_REPOSITORIES_TABLE))
            conn.execute(text(CREATE_GIT_REPOSITORIES_NAME_IDX))
            conn.execute(text(CREATE_GIT_REPOSITORIES_CATEGORY_IDX))
        return {"tables_created": ["git_repositories"]}

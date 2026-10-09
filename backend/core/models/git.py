from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from core.models.base import Base


class GitRepository(Base):
    __tablename__ = "git_repositories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    auth_type: Mapped[str] = mapped_column(String(50), nullable=False, default="token")
    credential_name: Mapped[str | None] = mapped_column(String(255))
    path: Mapped[str | None] = mapped_column(String(1000))
    verify_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    git_author_name: Mapped[str | None] = mapped_column(String(255))
    git_author_email: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_status: Mapped[str | None] = mapped_column(String(255))
    # Inbound git-webhook config (CI/CD pipeline — see doc/CICD_PIPELINE.md).
    # Fernet ciphertext of the GitHub HMAC secret / GitLab token; never returned
    # by the API. webhook_auto_deploy: when true a verified webhook dispatches
    # the deploy run immediately, otherwise it only marks the change request
    # reviewed and a human clicks "Deploy".
    webhook_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    # Python-side default (not server_default): AutoSchemaMigration's ADD COLUMN
    # path only renders `default=` for bools, so this backfills existing rows.
    webhook_auto_deploy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_git_repos_category", "category"),
        Index("idx_git_repos_active", "is_active"),
    )

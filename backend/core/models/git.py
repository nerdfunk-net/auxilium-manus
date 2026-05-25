from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.sql import func

from core.models.base import Base


class GitRepository(Base):
    __tablename__ = "git_repositories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    category = Column(String(50), nullable=False)
    url = Column(String(1000), nullable=False)
    branch = Column(String(255), nullable=False, default="main")
    auth_type = Column(String(50), nullable=False, default="token")
    credential_name = Column(String(255))
    path = Column(String(1000))
    verify_ssl = Column(Boolean, nullable=False, default=True)
    git_author_name = Column(String(255))
    git_author_email = Column(String(255))
    description = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    last_sync = Column(DateTime(timezone=True))
    sync_status = Column(String(255))
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_git_repos_category", "category"),
        Index("idx_git_repos_active", "is_active"),
    )

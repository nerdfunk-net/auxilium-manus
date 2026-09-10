from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.sql import func, text

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
    # Inbound git-webhook config (CI/CD pipeline — see doc/CICD_PIPELINE.md).
    # Fernet ciphertext of the GitHub HMAC secret / GitLab token; never returned
    # by the API. webhook_auto_deploy: when true a verified webhook dispatches
    # the deploy run immediately, otherwise it only marks the change request
    # reviewed and a human clicks "Deploy".
    webhook_secret_encrypted = Column(LargeBinary)
    webhook_auto_deploy = Column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
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

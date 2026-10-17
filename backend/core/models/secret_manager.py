from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from core.models.base import Base


class SecretManagerConnection(Base):
    """A configured connection to an external secret manager (OpenBao) used by
    workflow steps to generate, read, and rotate operational network secrets
    (TACACS+ keys, SNMP credentials, ...) at run time. See doc/SECRET_MANAGER_INTEGRATION.md.

    Separate from ``GitRepository``'s ``credentials`` table use and from
    ``doc/VAULT_INTEGRATION.md`` (which stores the app's *own* credentials and
    is deliberately read-only from workflow code) — this domain is
    write-capable from workflow steps by design.
    """

    __tablename__ = "secret_manager_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    backend: Mapped[str] = mapped_column(String(50), nullable=False)  # "openbao"
    # This connection's OWN auth material (AppRole secret_id), resolved via the
    # existing CredentialManager facade — a "generic" credential whose
    # username/password hold role_id/secret_id.
    credential_name: Mapped[str | None] = mapped_column(String(255))
    verify_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Backend-specific fields (not flat columns — variance is too wide to
    # share a column set without most columns being NULL for one backend):
    #   openbao:   {"addr": "...", "mount": "manus-network", "namespace": "..."}
    backend_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (Index("idx_secret_manager_conn_active", "is_active"),)

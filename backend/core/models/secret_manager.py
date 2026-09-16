from __future__ import annotations

from sqlalchemy import JSON, Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.sql import func

from core.models.base import Base


class SecretManagerConnection(Base):
    """A configured connection to an external secret manager (OpenBao or
    Infisical) used by workflow steps to generate, read, and rotate
    operational network secrets (TACACS+ keys, SNMP credentials, ...) at run
    time. See doc/SECRET_MANAGER_INTEGRATION.md.

    Separate from ``GitRepository``'s ``credentials`` table use and from
    ``doc/VAULT_INTEGRATION.md`` (which stores the app's *own* credentials and
    is deliberately read-only from workflow code) — this domain is
    write-capable from workflow steps by design.
    """

    __tablename__ = "secret_manager_connections"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    backend = Column(String(50), nullable=False)  # "openbao" | "infisical"
    # This connection's OWN auth material (AppRole secret_id / Infisical
    # client_secret), resolved via the existing CredentialManager facade —
    # a "generic" credential whose username/password hold role_id/secret_id
    # or client_id/client_secret respectively.
    credential_name = Column(String(255))
    verify_ssl = Column(Boolean, nullable=False, default=True)
    is_active = Column(Boolean, nullable=False, default=True)
    # Backend-specific fields (not flat columns — variance is too wide to
    # share a column set without most columns being NULL for one backend):
    #   openbao:   {"addr": "...", "mount": "manus-network", "namespace": "..."}
    #   infisical: {"site_url": "...", "project_id": "...", "environment": "prod"}
    backend_config = Column(JSON, nullable=False, default=dict)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (Index("idx_secret_manager_conn_active", "is_active"),)

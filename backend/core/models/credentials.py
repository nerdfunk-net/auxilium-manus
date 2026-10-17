from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class Credential(Base):
    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False, default="ssh")
    # Symmetric algorithm for "shared_secret" credentials (see
    # core.passphrase_cipher). NULL for every other credential type.
    algorithm: Mapped[str | None] = mapped_column(String(64), nullable=True)
    password_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    ssh_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    ssh_passphrase_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # Where the secret material lives: "local" (Fernet columns above) or "vault"
    # (OpenBao). String + Literal, matching `visibility` — AutoSchemaMigration has
    # no sqlalchemy.Enum support. `default=` (scalar) makes the auto-migration emit
    # NOT NULL DEFAULT 'local' so no APPLY_RISKY_DATABASE_MIGRATION is needed.
    storage_backend: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'local'"), default="local"
    )
    # KV v2 path suffix under the mount (e.g. "credentials/lab-switch-42"). NULL for
    # "local". Derived once at create; never rewritten on rename (see
    # doc/VAULT_INTEGRATION.md).
    vault_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Non-secret CSV of the logical secret field names stored in OpenBao for this
    # row ("password", "token", "ssh_key,ssh_passphrase"). Lets the list view and
    # has_* booleans render without a live OpenBao read.
    vault_secret_fields: Mapped[str | None] = mapped_column(String(255), nullable=True)
    valid_until: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    # Legacy free-text field, superseded by owner_user_id/visibility below.
    # Never populated by any code path; retained only for API backward compatibility.
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # "global" | "private". server_default backfills existing rows as global;
    # new rows created through the API default to "private" at the service layer.
    visibility: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'global'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index(
            "uq_credentials_global_name_source",
            "name",
            "source",
            unique=True,
            postgresql_where=text("visibility = 'global'"),
        ),
        Index(
            "uq_credentials_private_owner_name_source",
            "owner_user_id",
            "name",
            "source",
            unique=True,
            postgresql_where=text("visibility = 'private'"),
        ),
        Index("idx_credentials_source", "source"),
        Index("idx_credentials_owner", "owner"),
    )

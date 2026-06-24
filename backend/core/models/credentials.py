from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class Credential(Base):
    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False, default="ssh")
    password_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    ssh_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    ssh_passphrase_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    valid_until: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
        UniqueConstraint("name", "source", name="uq_credentials_name_source"),
        Index("idx_credentials_source", "source"),
        Index("idx_credentials_owner", "owner"),
    )

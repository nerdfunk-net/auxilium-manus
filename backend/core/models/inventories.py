from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class Inventory(Base):
    """Saved device-selection definitions (Nautobot source inventories)."""

    __tablename__ = "inventories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    conditions: Mapped[str] = mapped_column(Text, nullable=False)
    template_category: Mapped[str | None] = mapped_column(String(255))
    template_name: Mapped[str | None] = mapped_column(String(255))
    scope: Mapped[str] = mapped_column(String(50), nullable=False, default="global")
    group_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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
        Index("idx_inventory_scope_created_by", "scope", "created_by"),
        Index("idx_inventory_active_scope", "is_active", "scope"),
        Index("idx_inventory_group_path", "group_path"),
    )

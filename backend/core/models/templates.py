from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class Template(Base):
    """Jinja2 template used to configure network devices via Netmiko."""

    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="webeditor")
    template_type: Mapped[str] = mapped_column(String(50), nullable=False, default="jinja2")
    category: Mapped[str] = mapped_column(
        String(100), nullable=False, default="netmiko", index=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # JSON string: {name: {"value": str, "type": str}}
    variables: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # Legacy single-command field, kept for backward compatibility.
    pre_run_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON array of command strings run, in order, to populate preview variables.
    pre_run_commands: Mapped[str | None] = mapped_column(Text, nullable=True)
    pre_run_use_textfsm: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # JSON array of Nautobot attribute groups to fetch for the preview `nautobot`
    # variable (mirrors the get-nautobot-attributes step's list_of_attributes).
    nautobot_attributes: Mapped[str | None] = mapped_column(Text, nullable=True)
    credential_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
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
            "idx_templates_active_name",
            "name",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index("idx_templates_category", "category"),
    )

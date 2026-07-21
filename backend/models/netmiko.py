"""Pydantic models for ad-hoc Netmiko command execution (template preview)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NetmikoRunCommandsRequest(BaseModel):
    host: str = Field(..., min_length=1, description="Device IP address or hostname")
    platform: str | None = Field(default=None, description="Nautobot platform name")
    network_driver: str | None = Field(
        default=None, description="Nautobot platform network driver"
    )
    credential_id: int = Field(..., description="Stored SSH credential ID")
    commands: list[str] = Field(
        ..., min_length=1, description="Commands to execute, in order"
    )
    use_textfsm: bool = Field(
        default=False,
        description="Parse each command's output with TextFSM when a template exists",
    )


class NetmikoCommandEntry(BaseModel):
    """One command result, shaped like the workflow step's command namespace."""

    node_id: str
    name: str
    success: bool
    raw: str = ""
    parsed: Any = None


class NetmikoRunCommandsResponse(BaseModel):
    success: bool
    commands: list[NetmikoCommandEntry] = Field(default_factory=list)
    error: str | None = None


class NetmikoGetConfigsRequest(BaseModel):
    host: str = Field(..., min_length=1, description="Device IP address or hostname")
    platform: str | None = Field(default=None, description="Nautobot platform name")
    network_driver: str | None = Field(
        default=None, description="Nautobot platform network driver"
    )
    credential_id: int = Field(..., description="Stored SSH credential ID")


class NetmikoGetConfigsResponse(BaseModel):
    """Shaped like the parse-cisco-config step's entry for config_source="both"."""

    success: bool
    parsed: Any = None
    error: str | None = None

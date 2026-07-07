"""Pydantic models for ad-hoc Netmiko command execution (template pre-run test)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NetmikoRunCommandRequest(BaseModel):
    host: str = Field(..., min_length=1, description="Device IP address or hostname")
    platform: str | None = Field(default=None, description="Nautobot platform name")
    network_driver: str | None = Field(
        default=None, description="Nautobot platform network driver"
    )
    credential_id: int = Field(..., description="Stored SSH credential ID")
    command: str = Field(..., min_length=1, description="Command to execute")


class NetmikoRunCommandResponse(BaseModel):
    success: bool
    raw_output: str = ""
    parsed_output: Any = None
    error: str | None = None

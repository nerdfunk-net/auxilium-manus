"""Normalized Cisco ACI (APIC) models - the only shapes workflow steps and tools see.

Raw APIC payloads stay inside ``services/aci/``; a future payload change is fixed there.
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.source_keys import SOURCE_ID_PATTERN

AciRole = Literal["leaf", "spine"]


class AciDevice(BaseModel):
    """One fabric switch (leaf or spine), merged from ``fabricNode`` and ``topSystem``."""

    model_config = ConfigDict(frozen=True)

    node_id: int
    name: str
    role: AciRole
    pod_id: int | None = None
    model: str | None = None
    serial_number: str | None = None
    software_version: str | None = None
    # fabricNode.fabricSt: active / inactive / discovering / ...
    fabric_state: str | None = None
    # topSystem.state: in-service / out-of-service / ...
    system_state: str | None = None
    # Address of the TEP (fabric-internal). NOT a management address.
    tep_address: str | None = None
    # Out-of-band, else in-band management IPv4; ``None`` when the fabric has none configured.
    management_ip: str | None = None
    oob_ip: str | None = None
    inb_ip: str | None = None
    dn: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


# --- source configuration API (Settings -> Sources) -------------------------------------------
# Request models forbid unknown fields; the credential is a vault reference, never a password.

_SOURCE_ID_REGEX = SOURCE_ID_PATTERN.pattern


class AciSourceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., pattern=_SOURCE_ID_REGEX, max_length=64)
    url: str = Field(..., min_length=1)
    credential_id: int = Field(..., gt=0)
    verify_ssl: bool = True
    timeout: float = Field(default=30.0, ge=1, le=120)


class AciSourceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, min_length=1)
    credential_id: int | None = Field(default=None, gt=0)
    verify_ssl: bool | None = None
    timeout: float | None = Field(default=None, ge=1, le=120)


class AciTestConnectionRequest(BaseModel):
    """Unsaved form values, or ``source_id`` to test stored credentials."""

    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, min_length=1)
    credential_id: int | None = Field(default=None, gt=0)
    verify_ssl: bool = True
    timeout: float = Field(default=30.0, ge=1, le=120)
    source_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_source_or_inline(self) -> Self:
        has_source = bool((self.source_id or "").strip())
        has_inline = bool((self.url or "").strip()) and self.credential_id is not None
        if has_source == has_inline:
            raise ValueError("Provide either source_id or both url and credential_id")
        return self


class AciSourceResponse(BaseModel):
    source_id: str
    url: str
    verify_ssl: bool
    timeout: float
    credential_id: int | None = None
    credential_name: str | None = None


class AciSourceListResponse(BaseModel):
    sources: list[AciSourceResponse]
    total: int


class AciTestConnectionResponse(BaseModel):
    success: bool
    message: str
    # APIC software version reported at login, e.g. "6.1(4h)".
    version: str | None = None


# --- device preview (workflow step UI) --------------------------------------------------------


class AciDevicePreviewRequest(BaseModel):
    """Filters are validated by ``AciDeviceFilters.from_config`` in the router."""

    model_config = ConfigDict(extra="forbid")

    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=25, ge=1, le=100)


class AciDevicePreviewItem(BaseModel):
    """Inventory summary shown in the step's preview; deliberately omits the raw record."""

    node_id: int
    name: str
    role: AciRole
    pod_id: int | None = None
    model: str | None = None
    serial_number: str | None = None
    software_version: str | None = None
    fabric_state: str | None = None
    management_ip: str | None = None


class AciDevicePreviewResponse(BaseModel):
    devices: list[AciDevicePreviewItem]
    truncated: bool

"""Canonical workflow envelope types (see doc/MANUS_BASIS_DATATYPE.md)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Capability(str, Enum):
    """A discrete, independently-acquired property of a DeviceContext."""

    IDENTITY = "identity"
    ATTRIBUTES = "attributes"
    RUNNING_CONFIG = "running_config"
    STARTUP_CONFIG = "startup_config"
    PARSED = "parsed"
    PENDING_COMMANDS = "pending_commands"


class DeviceStatus(str, Enum):
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


_STATUS_RANK: dict[DeviceStatus, int] = {
    DeviceStatus.FAILED: 3,
    DeviceStatus.SKIPPED: 2,
    DeviceStatus.PENDING: 1,
    DeviceStatus.OK: 0,
}


def worst_device_status(left: DeviceStatus, right: DeviceStatus) -> DeviceStatus:
    return left if _STATUS_RANK[left] >= _STATUS_RANK[right] else right


class ArtifactRef(BaseModel):
    """Pointer to content stored outside the envelope."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    kind: str
    media_type: str = "text/plain"
    size_bytes: int | None = None
    sha256: str | None = None
    created_at: str = Field(default_factory=now_iso)


class CommandResult(BaseModel):
    """Metadata for one CLI command. Raw output is an ArtifactRef, not inlined."""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    command: str
    success: bool
    executed_at: str = Field(default_factory=now_iso)
    output_ref: ArtifactRef | None = None
    summary: str | None = None


class DeviceError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    step_id: str
    code: str
    message: str
    occurred_at: str = Field(default_factory=now_iso)


class DeviceContext(BaseModel):
    """Everything the workflow knows about one device. Enriched in place by steps."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    hostname: str
    platform: str | None = None
    network_driver: str | None = None
    primary_ip4: str | None = None
    source: str = ""
    source_id: str = ""

    attribute_bags: dict[str, dict[str, Any]] = Field(default_factory=dict)
    running_config_ref: ArtifactRef | None = None
    startup_config_ref: ArtifactRef | None = None
    parsed: dict[str, Any] = Field(default_factory=dict)
    command_results: dict[str, list[CommandResult]] = Field(default_factory=dict)

    capabilities: set[Capability] = Field(default_factory=set)
    status: DeviceStatus = DeviceStatus.PENDING
    errors: list[DeviceError] = Field(default_factory=list)

    @field_serializer("capabilities")
    def serialize_capabilities(self, capabilities: set[Capability]) -> list[str]:
        return sorted(cap.value for cap in capabilities)

    @field_validator("capabilities", mode="before")
    @classmethod
    def parse_capabilities(cls, value: Any) -> set[Capability]:
        if value is None:
            return set()
        if isinstance(value, set):
            return {
                Capability(item) if not isinstance(item, Capability) else item
                for item in value
            }
        if isinstance(value, (list, tuple)):
            return {Capability(item) for item in value}
        raise TypeError(f"capabilities must be a set or list, got {type(value)!r}")


class WorkflowContext(BaseModel):
    """The single envelope that flows along every edge of the workflow graph."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    workflow_id: str
    schema_version: int = 2

    devices: dict[str, DeviceContext] = Field(default_factory=dict)
    pending_commands: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def provided_capabilities(self) -> set[Capability]:
        """Capabilities present on every device (vacuously full when empty)."""
        if not self.devices:
            return set(Capability)
        capability_sets = [device.capabilities for device in self.devices.values()]
        return set.intersection(*capability_sets)

    def provided_parsed_keys(self) -> set[str]:
        """Parser keys present on every device."""
        if not self.devices:
            return set()
        parsed_sets = [set(device.parsed.keys()) for device in self.devices.values()]
        return set.intersection(*parsed_sets)


class StepOutcome(BaseModel):
    """A named exit path from a step, carrying the enriched context."""

    model_config = ConfigDict(extra="forbid")

    name: str
    context: WorkflowContext


def bare_hostname(primary_ip4: str | None, fallback: str) -> str:
    """Derive a bare SSH hostname from primary_ip4 (strip CIDR) or fallback."""
    if primary_ip4:
        return primary_ip4.split("/")[0]
    return fallback

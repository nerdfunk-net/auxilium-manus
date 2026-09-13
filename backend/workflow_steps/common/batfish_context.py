"""Shared Batfish snapshot reference: written by batfish-init-snapshot into
WorkflowContext.metadata, read by the three query steps. One consolidated
key ("batfish") carries host/port/network/snapshot together so downstream
query steps need no source_id config of their own -- see
doc/BATFISH_INTEGRATION.md "Why WorkflowContext.metadata, not a new
Capability" for the full reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass

from models.workflow_context import WorkflowContext
from services.batfish.credentials import BatfishConnection

_METADATA_KEY = "batfish"


@dataclass(frozen=True)
class BatfishSnapshotRef:
    connection: BatfishConnection
    network: str
    snapshot: str


def resolve_batfish_snapshot(context: WorkflowContext) -> BatfishSnapshotRef:
    raw = context.metadata.get(_METADATA_KEY)
    if not isinstance(raw, dict):
        raise ValueError(
            "No Batfish snapshot found in this run -- add an Init Batfish "
            "Snapshot step upstream of this step."
        )
    try:
        return BatfishSnapshotRef(
            connection=BatfishConnection(host=str(raw["host"]), port=int(raw["port"])),
            network=str(raw["network"]),
            snapshot=str(raw["snapshot"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Batfish snapshot metadata is malformed: {exc}") from exc


def store_batfish_snapshot(
    context: WorkflowContext,
    *,
    connection: BatfishConnection,
    network: str,
    snapshot: str,
) -> WorkflowContext:
    metadata = dict(context.metadata)
    metadata[_METADATA_KEY] = {
        "host": connection.host,
        "port": connection.port,
        "network": network,
        "snapshot": snapshot,
    }
    return context.model_copy(update={"metadata": metadata})

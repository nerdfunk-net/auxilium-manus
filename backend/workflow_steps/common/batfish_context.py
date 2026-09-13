"""Shared Batfish snapshot reference: written by batfish-init-snapshot into
WorkflowContext.metadata, read by the three query steps. One consolidated
key ("batfish") carries host/port/network/snapshot together so downstream
query steps need no source_id config of their own -- see
doc/BATFISH_INTEGRATION.md "Why WorkflowContext.metadata, not a new
Capability" for the full reasoning.

resolve_batfish_snapshot_ref additionally lets a query step target a network
directly via its own batfish_source_id/network(/snapshot) config, bypassing
this run's metadata entirely -- explicit step config always wins when both
are set, so a query workflow with no Init step of its own can still query a
standing, independently-refreshed network (e.g. one rebuilt nightly in git
mode by a Schedule).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

from models.workflow_context import WorkflowContext
from services.batfish.credentials import BatfishConnection
from services.batfish.source_config_service import BatfishSourceConfigService

if TYPE_CHECKING:
    from core.models.runs import WorkflowRun
    from services.batfish.client import BatfishService

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


async def resolve_batfish_snapshot_ref(
    *,
    context: WorkflowContext,
    config: dict[str, Any],
    run: WorkflowRun,
    batfish: BatfishService,
) -> BatfishSnapshotRef:
    """Resolve the snapshot a query step should read.

    When config has both batfish_source_id and network set, resolves and
    targets that network directly (defaulting to its most recent snapshot by
    creation timestamp when config["snapshot"] is blank), ignoring this run's
    metadata entirely. Otherwise falls back to resolve_batfish_snapshot(context)
    unchanged.
    """
    source_id = str(config.get("batfish_source_id") or "").strip()
    network = str(config.get("network") or "").strip()
    if not (source_id and network):
        return resolve_batfish_snapshot(context)

    db = object_session(run)
    if db is None:
        raise RuntimeError("resolve_batfish_snapshot_ref: WorkflowRun has no active DB session")
    connection = BatfishSourceConfigService(db).resolve_connection(source_id)

    snapshot = str(config.get("snapshot") or "").strip()
    if not snapshot:
        entries = await batfish.list_snapshots_with_metadata(connection, batfish_network=network)
        if not entries:
            raise ValueError(
                f"No Batfish snapshots found in network {network!r} -- run Init Batfish "
                "Snapshot against this network first, or set 'snapshot' explicitly."
            )
        entries_sorted = sorted(
            entries, key=lambda e: e.get("metadata", {}).get("creationTimestamp", "")
        )
        snapshot = str(entries_sorted[-1]["name"])

    return BatfishSnapshotRef(connection=connection, network=network, snapshot=snapshot)


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

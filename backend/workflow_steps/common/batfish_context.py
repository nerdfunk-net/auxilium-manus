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

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.batfish.credentials import BatfishConnection
from services.batfish.query_helpers import (
    assert_batfish_network_exists,
    resolve_latest_snapshot_name,
)
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

    # Must happen before anything below touches BatfishService._get_session()
    # for this network (both the resolve_latest_snapshot_name call below and
    # the query the caller runs afterward do) -- see
    # assert_batfish_network_exists' docstring for why.
    await assert_batfish_network_exists(batfish, connection, network)

    snapshot = str(config.get("snapshot") or "").strip()
    if not snapshot:
        snapshot = await resolve_latest_snapshot_name(batfish, connection, network)

    return BatfishSnapshotRef(connection=connection, network=network, snapshot=snapshot)


def devices_from_nodes(rows: list[dict[str, Any]]) -> dict[str, DeviceContext]:
    """Dedupe a Batfish answer's ``Node`` column into one DeviceContext per
    distinct node -- the same Batfish-sourced identity shape
    batfish-routing-table's own ``devices`` outcome already builds (kept as
    an independent inline copy there, not refactored onto this helper, so
    this addition carries zero behavior risk for that step). Used by
    batfish-start-run's executor ("Get from Batfish") to populate real
    devices from a snapshot's node list.
    """
    device_nodes: dict[str, DeviceContext] = {}
    for row in rows:
        node = row.get("Node")
        if not node or node in device_nodes:
            continue
        device_nodes[node] = DeviceContext(
            id=node,
            name=node,
            hostname=node,
            source="batfish",
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
    return device_nodes


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

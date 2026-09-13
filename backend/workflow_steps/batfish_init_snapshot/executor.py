"""Executor for the batfish-init-snapshot step.

Assembles this run's device running-configs into a fresh Batfish snapshot
(one Batfish network per Manus workflow, one snapshot per run -- see
doc/BATFISH_INTEGRATION.md "Snapshot lifecycle") and records the resulting
(host, port, network, snapshot) in WorkflowContext.metadata for the three
downstream query steps (Routing Table, Path Check, ACL Check) to read via
workflow_steps.common.batfish_context.resolve_batfish_snapshot.

Not fan-out-safe: like store-artifact/git steps, this needs every device's
config together in one upload, so it must run after a Fan In in a
fanned-out workflow, never inside the fanned-out branch.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.batfish.common.exceptions import BatfishAPIError
from services.batfish.source_config_service import BatfishSourceConfigService
from workflow_steps.batfish_init_snapshot.config import get_config
from workflow_steps.common.batfish_context import store_batfish_snapshot
from workflow_steps.common.content_resolver import list_exportable_content

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "batfish-init-snapshot"


async def _write_device_configs(
    *,
    context: WorkflowContext,
    artifact_service: ArtifactService,
    configs_dir: Path,
) -> list[str]:
    """Write each device's running-config into configs_dir. Returns skipped device ids."""
    skipped: list[str] = []
    for device_id, device in context.devices.items():
        items = list_exportable_content(device, content_source="running_config")
        if not items:
            skipped.append(device_id)
            continue
        text = await artifact_service.resolve(items[0].artifact_ref)
        (configs_dir / f"{device_id}.cfg").write_text(text, encoding="utf-8")
    return skipped


async def _sweep_old_snapshots(
    batfish: Any, connection: Any, *, network: str, retain: int
) -> None:
    """Best-effort retention: delete every snapshot beyond the most recent `retain`.

    Never fails the step -- a retention failure is logged and swallowed.
    Sorts by metadata.creationTimestamp, NOT by name (snapshot names like
    "run-42" are not chronologically sortable by string comparison).
    """
    if retain <= 0:
        return
    try:
        entries = await batfish.list_snapshots_with_metadata(connection, batfish_network=network)
    except BatfishAPIError as exc:
        logger.warning("%s: retention sweep skipped, could not list snapshots: %s", _STEP_ID, exc)
        return

    entries_sorted = sorted(
        entries, key=lambda e: e.get("metadata", {}).get("creationTimestamp", "")
    )
    stale = entries_sorted[:-retain] if len(entries_sorted) > retain else []
    for entry in stale:
        name = entry.get("name")
        if not name:
            continue
        try:
            await batfish.delete_snapshot(connection, batfish_network=network, snapshot_name=name)
        except BatfishAPIError as exc:
            logger.warning("%s: failed to delete stale snapshot %s: %s", _STEP_ID, name, exc)


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del device_sessions  # unused: Batfish is reached via pybatfish, not Netmiko

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    merged_config = {**get_config(), **config}
    source_id = str(merged_config.get("batfish_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: batfish_source_id is required")
    retain = int(merged_config.get("retain_snapshots") or 0)

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    connection = BatfishSourceConfigService(db).resolve_connection(source_id)

    network = f"manus-workflow-{context.workflow_id}"
    snapshot_name = f"run-{run.id}"

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d network=%s snapshot=%s",
        _STEP_ID,
        run.id,
        node_id,
        len(context.devices),
        network,
        snapshot_name,
    )

    batfish = service_factory.get_batfish_app_service()

    with tempfile.TemporaryDirectory(prefix="batfish-snapshot-") as tmpdir:
        configs_dir = Path(tmpdir) / "configs"
        configs_dir.mkdir()
        skipped = await _write_device_configs(
            context=context, artifact_service=artifact_service, configs_dir=configs_dir
        )
        if skipped:
            logger.warning(
                "%s: devices with no running_config skipped run_id=%s devices=%s",
                _STEP_ID,
                run.id,
                skipped,
            )
        if len(skipped) == len(context.devices):
            raise RuntimeError(f"{_STEP_ID}: no device has a running_config to snapshot")

        await batfish.init_snapshot(
            connection,
            batfish_network=network,
            snapshot_name=snapshot_name,
            snapshot_dir=str(configs_dir.parent),
            overwrite=True,
        )

    await _sweep_old_snapshots(batfish, connection, network=network, retain=retain)

    new_context = store_batfish_snapshot(
        context, connection=connection, network=network, snapshot=snapshot_name
    )

    initialized = len(context.devices) - len(skipped)
    logger.info(
        "%s finished run_id=%s snapshot=%s initialized=%d skipped=%d",
        _STEP_ID,
        run.id,
        snapshot_name,
        initialized,
        len(skipped),
    )

    return [
        StepOutcome(
            name="success",
            context=new_context,
            summary=(
                f"Snapshot {snapshot_name} initialized "
                f"({initialized} device(s), {len(skipped)} skipped)"
            ),
        )
    ]

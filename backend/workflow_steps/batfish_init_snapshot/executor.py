"""Executor for the batfish-init-snapshot step.

Two config sources (see doc/BATFISH_INTEGRATION.md "Config source: live vs.
git"):

- "live" (default): assembles this run's device running-configs into a
  fresh Batfish snapshot (one Batfish network per Manus workflow by default,
  one snapshot per run -- see "Snapshot lifecycle"). Not concurrency-safe:
  like store-artifact/git steps, this needs every device's config together
  in one upload, so it must run after a Fan In in a fanned-out workflow,
  never inside the fanned-out branch -- and never on two independent
  sibling branches in the same run, which would race the same upload.
- "git": reads already-collected configs from a Git repository instead of
  context.devices -- no live device contact at all, suitable for refreshing
  a production-scale network on a schedule (see
  workflow_steps.common.batfish_git_source). Ignores context.devices
  entirely; pair with an upstream get-batfish-devices step to satisfy the
  canvas's requires: [identity] connection rule without a real
  device-selection step.

An optional network_name config override lets either mode target a network
with a stable name independent of workflow_id (e.g. a production network
refreshed nightly by a Schedule), instead of the default
"manus-workflow-{workflow_id}".

The resulting (host, port, network, snapshot) is recorded in
WorkflowContext.metadata for the three downstream query steps (Routing
Table, Path Check, ACL Check) to read via
workflow_steps.common.batfish_context.resolve_batfish_snapshot (or bypassed
entirely via their own batfish_source_id/network config -- see
resolve_batfish_snapshot_ref).
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from repositories.run_repository import RunRepository
from services.artifacts import ArtifactService
from services.batfish.common.exceptions import BatfishAPIError
from services.batfish.source_config_service import BatfishSourceConfigService
from services.git.sync import agit_checkout
from services.workflow_context.device_template import sanitize_path_segment
from workflow_steps.batfish_init_snapshot.config import get_config
from workflow_steps.common.batfish_context import store_batfish_snapshot
from workflow_steps.common.batfish_git_source import (
    collect_git_source_files,
    copy_git_source_files_into,
)
from workflow_steps.common.content_resolver import list_exportable_content
from workflow_steps.common.git_repository_loader import load_git_repository
from workflow_steps.common.partial_outcomes import mark_device_failed
from workflow_steps.common.step_flags import parse_bool_flag

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "batfish-init-snapshot"
_DEFAULT_NETWORK_RE = re.compile(r"manus-workflow-(\d+)")
_CONFIG_SOURCES = frozenset({"live", "git"})


@dataclass(frozen=True)
class _InitSummary:
    text: str
    log_suffix: str
    skipped: tuple[str, ...] = ()


def _workflow_number(workflow_id: object) -> int | None:
    try:
        return int(str(workflow_id))
    except ValueError:
        return None


async def _write_device_configs(
    *,
    context: WorkflowContext,
    artifact_service: ArtifactService,
    configs_dir: Path,
) -> list[str]:
    """Write each device's running-config into configs_dir. Returns skipped device ids."""
    skipped: list[str] = []
    used_names: set[str] = set()
    for device_id, device in context.devices.items():
        items = list_exportable_content(device, content_source="running_config")
        if not items:
            skipped.append(device_id)
            continue
        text = await artifact_service.resolve(items[0].artifact_ref)
        # Two ids can sanitise to the same name ("a/b" and "a_b"): never overwrite one
        # device's config with another's.
        stem = sanitize_path_segment(device_id)
        name, suffix = stem, 1
        while name in used_names:
            suffix += 1
            name = f"{stem}_{suffix}"
        used_names.add(name)
        (configs_dir / f"{name}.cfg").write_text(text, encoding="utf-8")
    return skipped


_SNAPSHOT_RUN_RE = re.compile(r"^run-(\d+)(?:-|$)")


async def _sweep_old_snapshots(
    batfish: Any,
    connection: Any,
    *,
    network: str,
    retain: int,
    active_run_ids: frozenset[int] = frozenset(),
) -> None:
    """Best-effort retention: delete every snapshot beyond the most recent `retain`.

    A snapshot of a run that is still pending/running/paused is never deleted, so a concurrent
    run on a shared network keeps the snapshot it is querying.

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
        owner = _SNAPSHOT_RUN_RE.match(str(name))
        if owner is not None and int(owner.group(1)) in active_run_ids:
            continue
        try:
            await batfish.delete_snapshot(connection, batfish_network=network, snapshot_name=name)
        except BatfishAPIError as exc:
            logger.warning("%s: failed to delete stale snapshot %s: %s", _STEP_ID, name, exc)


async def _init_from_live(
    *,
    context: WorkflowContext,
    artifact_service: ArtifactService,
    batfish: Any,
    connection: Any,
    network: str,
    snapshot_name: str,
    allow_partial_snapshot: bool = False,
) -> _InitSummary:
    with tempfile.TemporaryDirectory(prefix="batfish-snapshot-") as tmpdir:
        configs_dir = Path(tmpdir) / "configs"
        configs_dir.mkdir()
        skipped = await _write_device_configs(
            context=context, artifact_service=artifact_service, configs_dir=configs_dir
        )
        if skipped:
            logger.warning(
                "%s: devices with no running_config skipped devices=%s",
                _STEP_ID,
                skipped,
            )
        if len(skipped) == len(context.devices):
            raise RuntimeError(f"{_STEP_ID}: no device has a running_config to snapshot")
        if skipped and not allow_partial_snapshot:
            names = ", ".join(sorted(skipped)[:5]) + ("..." if len(skipped) > 5 else "")
            raise ValueError(
                f"{_STEP_ID}: {len(skipped)} device(s) have no running config ({names}); the "
                "snapshot would not describe the whole network. Fix the upstream step, or set "
                "'allow_partial_snapshot' to build it from the devices that have one."
            )

        await batfish.init_snapshot(
            connection,
            batfish_network=network,
            snapshot_name=snapshot_name,
            snapshot_dir=str(configs_dir.parent),
            overwrite=True,
        )

    initialized = len(context.devices) - len(skipped)
    return _InitSummary(
        text=(
            f"Snapshot {snapshot_name} initialized "
            f"({initialized} device(s), {len(skipped)} skipped)"
        ),
        log_suffix=f"config_source=live initialized={initialized} skipped={len(skipped)}",
        skipped=tuple(skipped),
    )


async def _init_from_git(
    *,
    merged_config: dict[str, Any],
    batfish: Any,
    connection: Any,
    network: str,
    snapshot_name: str,
) -> _InitSummary:
    raw_repository_id = merged_config.get("git_repository_id")
    if raw_repository_id in (None, ""):
        raise ValueError(f"{_STEP_ID}: git_repository_id is required when config_source is 'git'")
    git_repository_id = int(raw_repository_id)
    base_path = str(merged_config.get("base_path") or "")
    glob_pattern = str(merged_config.get("glob_pattern") or "").strip()
    if not glob_pattern:
        raise ValueError(f"{_STEP_ID}: glob_pattern is required when config_source is 'git'")

    repository = await asyncio.to_thread(load_git_repository, git_repository_id)

    with tempfile.TemporaryDirectory(prefix="batfish-snapshot-") as tmpdir:
        configs_dir = Path(tmpdir) / "configs"
        configs_dir.mkdir()
        # The lease covers only the reads; the upload to Batfish works on the copies (C2-06).
        async with agit_checkout(
            repository, allow_stale=parse_bool_flag(merged_config, "allow_stale_repository")
        ) as repo_dir:
            matched_files = await asyncio.to_thread(
                collect_git_source_files,
                repo_root=repo_dir,
                base_path=base_path,
                glob_pattern=glob_pattern,
            )
            await asyncio.to_thread(copy_git_source_files_into, configs_dir, matched_files)

        await batfish.init_snapshot(
            connection,
            batfish_network=network,
            snapshot_name=snapshot_name,
            snapshot_dir=str(configs_dir.parent),
            overwrite=True,
        )

    return _InitSummary(
        text=f"Snapshot {snapshot_name} initialized ({len(matched_files)} config file(s) from git)",
        log_suffix=f"config_source=git files={len(matched_files)}",
    )


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

    merged_config = {**get_config(), **config}
    config_source = str(merged_config.get("config_source") or "live").strip().lower()
    if config_source not in _CONFIG_SOURCES:
        raise ValueError(f"{_STEP_ID}: config_source must be one of {sorted(_CONFIG_SOURCES)}")

    if config_source == "live" and not context.devices:
        return [StepOutcome(name="success", context=context)]

    source_id = str(merged_config.get("batfish_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: batfish_source_id is required")
    retain = int(merged_config.get("retain_snapshots") or 0)

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    connection = BatfishSourceConfigService(db).resolve_connection(source_id)

    network = str(merged_config.get("network_name") or "").strip() or (
        f"manus-workflow-{context.workflow_id}"
    )
    # B5: a custom network_name may be a deliberately shared network, but it must not
    # collide with *another workflow's* default network (overwrite=True + retention
    # sweep would destroy that workflow's snapshots).
    other = _DEFAULT_NETWORK_RE.fullmatch(network)
    if other is not None and int(other.group(1)) != _workflow_number(context.workflow_id):
        raise ValueError(
            f"{_STEP_ID}: network_name {network!r} is the default network of workflow "
            f"{other.group(1)}; choose a different name"
        )
    # One snapshot per init node: two init steps in one run must not replace each other.
    snapshot_name = f"run-{run.id}-{sanitize_path_segment(node_id)}"

    logger.info(
        "%s started run_id=%s node_id=%s config_source=%s devices=%d network=%s snapshot=%s",
        _STEP_ID,
        run.id,
        node_id,
        config_source,
        len(context.devices),
        network,
        snapshot_name,
    )

    batfish = service_factory.get_batfish_app_service()

    if config_source == "git":
        summary = await _init_from_git(
            merged_config=merged_config,
            batfish=batfish,
            connection=connection,
            network=network,
            snapshot_name=snapshot_name,
        )
    else:
        summary = await _init_from_live(
            context=context,
            artifact_service=artifact_service,
            batfish=batfish,
            connection=connection,
            network=network,
            snapshot_name=snapshot_name,
            allow_partial_snapshot=parse_bool_flag(merged_config, "allow_partial_snapshot"),
        )

    await _sweep_old_snapshots(
        batfish,
        connection,
        network=network,
        retain=retain,
        active_run_ids=frozenset(RunRepository(db).list_active_run_ids()),
    )

    new_context = store_batfish_snapshot(
        context, connection=connection, network=network, snapshot=snapshot_name
    )

    logger.info(
        "%s finished run_id=%s snapshot=%s %s",
        _STEP_ID,
        run.id,
        snapshot_name,
        summary.log_suffix,
    )

    if not summary.skipped:
        return [StepOutcome(name="success", context=new_context, summary=summary.text)]

    # allow_partial_snapshot: the devices left out of the snapshot leave through 'failure'
    skipped_ids = set(summary.skipped)
    ok_devices = {k: v for k, v in new_context.devices.items() if k not in skipped_ids}
    failed_devices = {
        device_id: mark_device_failed(
            context.devices[device_id],
            node_id=node_id,
            step_id=_STEP_ID,
            code="running_config_missing",
            message="no running config, device is not part of the snapshot",
        )
        for device_id in summary.skipped
    }
    return [
        StepOutcome(
            name="success",
            context=new_context.model_copy(update={"devices": ok_devices}),
            summary=summary.text,
        ),
        StepOutcome(
            name="failure",
            context=new_context.model_copy(update={"devices": failed_devices}),
            summary=f"{len(failed_devices)} device(s) not part of the snapshot",
        ),
    ]

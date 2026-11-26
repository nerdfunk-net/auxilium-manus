"""Pre- and post-replace config diff checks of configure-replace-config."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
)
from services.artifacts import ArtifactService
from services.pyats.credentials import PyATSCredentials
from services.workflow_context.node_result import set_node_result
from workflow_steps.common.device_runner import Fail
from workflow_steps.common.failure_records import COMMAND_FAILED
from workflow_steps.configure_replace_config.shim_jobs import (
    STEP_ID,
    run_diff,
)

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


DIFF_ARTIFACT_KIND_PRE = "configure_replace_pre_diff"
DIFF_ARTIFACT_KIND_POST = "configure_replace_post_diff"


def diff_has_changes(diff_text: str) -> bool:
    """True when a 'show archive config differences' response represents a
    real difference.

    The command always prints a '!Contextual Config Diffs:' header line, even
    when there is nothing to report -- Cisco IOS then follows it with
    '!No changes were found' rather than leaving the rest of the output
    blank. A plain truthiness/``.strip()`` check on the raw text therefore
    treats every call as a diff; this walks the non-blank lines and ignores
    only those two known no-op lines.
    """
    for line in diff_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lstrip("!").strip().lower()
        if lowered in ("contextual config diffs:", "no changes were found"):
            continue
        return True
    return False


def build_diff_command(*, file_system: str, destination_filename: str) -> str:
    target = f"{file_system}{destination_filename}"
    return f"show archive config differences system:running-config {target}"


def device_with_diff_refs(
    device: DeviceContext,
    node_id: str,
    *,
    pre_diff_artifact_ref: Any | None,
    post_diff_artifact_ref: Any | None,
) -> DeviceContext:
    """Record diff artifact refs on the device's parsed output, independent of
    whether the device ends up succeeding or failing."""
    if pre_diff_artifact_ref is None and post_diff_artifact_ref is None:
        return device
    entry: dict[str, Any] = {"kind": "configure_replace_diff"}
    if pre_diff_artifact_ref is not None:
        entry["pre_diff_artifact_ref"] = pre_diff_artifact_ref.model_dump(mode="json")
    if post_diff_artifact_ref is not None:
        entry["post_diff_artifact_ref"] = post_diff_artifact_ref.model_dump(mode="json")
    parsed = set_node_result(device.parsed, node_id, "configure_replace_diff", entry)
    return device.model_copy(
        update={"parsed": parsed, "capabilities": device.capabilities | {Capability.PARSED}}
    )


@dataclass(frozen=True)
class Target:
    """Everything a device needs before any shim call: its testbed bag, source credentials
    and the shim device description."""

    bag: dict[str, Any]
    source_id: str
    shim: Any
    shim_credentials: PyATSCredentials
    shim_device: dict[str, Any]
    job_timeout: float  # seconds; every shim job of this device gets it


@dataclass(frozen=True)
class PreDiff:
    """Result of the pre-replace diff check: either the finished (skipped) device, or the
    artifact of the pending diff (None when no check ran / it failed)."""

    skipped: DeviceContext | None = None
    artifact_ref: Any | None = None


async def pre_replace_diff(
    target: Target,
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    diff_command: str,
    destination_filename: str,
    file_system: str,
    timeout_minutes: int,
    artifact_service: ArtifactService,
    context_run_id: str,
) -> PreDiff:
    diff_ok, pre_diff_text, diff_err = await run_diff(
        target.shim,
        target.shim_credentials,
        shim_device=target.shim_device,
        diff_command=diff_command,
        timeout=target.job_timeout,
    )
    if diff_ok and not diff_has_changes(pre_diff_text):
        entry = {
            "kind": "configure_replace",
            "confirmed": False,
            "skipped": True,
            "reason": "no_pending_changes",
            "destination_filename": destination_filename,
            "file_system": file_system,
            "timeout_minutes": timeout_minutes,
        }
        parsed = set_node_result(device.parsed, node_id, "configure_replace", entry)
        enriched = device.model_copy(
            update={
                "parsed": parsed,
                "capabilities": device.capabilities | {Capability.PARSED},
                "status": DeviceStatus.OK,
            }
        )
        logger.info(
            "%s skipped device=%s host=%s reason=no_pending_changes",
            STEP_ID,
            device_id,
            target.bag.get("host"),
        )
        return PreDiff(skipped=enriched)
    if diff_ok:
        artifact_ref = await artifact_service.store(
            content=pre_diff_text,
            kind=DIFF_ARTIFACT_KIND_PRE,
            device_id=device_id,
            run_id=context_run_id,
            media_type="text/plain",
        )
        return PreDiff(artifact_ref=artifact_ref)
    logger.warning(
        "%s pre-replace diff check failed device=%s host=%s error=%s -- proceeding "
        "with replace unverified",
        STEP_ID,
        device_id,
        target.bag.get("host"),
        diff_err,
    )
    return PreDiff()


async def verify_after_replace(
    target: Target,
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    diff_command: str,
    destination_filename: str,
    file_system: str,
    pre_diff_artifact_ref: Any | None,
    artifact_service: ArtifactService,
    context_run_id: str,
) -> Fail | None:
    """Diff the running config against the replacement file. Returns a ``Fail`` (carrying the
    device with its diff refs) when the check fails or the configs still differ, else None."""
    diff_ok, post_diff_text, diff_err = await run_diff(
        target.shim,
        target.shim_credentials,
        shim_device=target.shim_device,
        diff_command=diff_command,
        timeout=target.job_timeout,
    )
    if not diff_ok:
        return Fail(
            "post_verify_failed",
            f"'configure confirm' succeeded but the post-replace diff check failed "
            f"({diff_err}); the running configuration could not be verified against "
            f"{file_system}{destination_filename}",
            device=device_with_diff_refs(
                device,
                node_id,
                pre_diff_artifact_ref=pre_diff_artifact_ref,
                post_diff_artifact_ref=None,
            ),
            failure=COMMAND_FAILED,
        )
    if not diff_has_changes(post_diff_text):
        return None
    post_diff_artifact_ref = await artifact_service.store(
        content=post_diff_text,
        kind=DIFF_ARTIFACT_KIND_POST,
        device_id=device_id,
        run_id=context_run_id,
        media_type="text/plain",
    )
    return Fail(
        "diff_mismatch",
        f"Running configuration still differs from "
        f"{file_system}{destination_filename} after 'configure replace'/"
        f"'configure confirm' succeeded; see the stored diff artifact "
        f"(artifact_id={post_diff_artifact_ref.artifact_id}) for details",
        device=device_with_diff_refs(
            device,
            node_id,
            pre_diff_artifact_ref=pre_diff_artifact_ref,
            post_diff_artifact_ref=post_diff_artifact_ref,
        ),
    )

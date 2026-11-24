"""The loop shared by secret-get, secret-set and secret-generate (P-C pilot, W10-01).

Each step supplies what is its own (config parsing, one per-device operation against the
Secret Manager, the metadata keys it has always written); this module owns the rest: the empty
guard, the database session, the per-device secret paths, the sequential run, the loss of the
connection and the outcomes.

* A device whose secret path is invalid or collides with another device's fails alone.
* An operation returns the updated device, or :class:`Fail` for a device-level miss, or raises.
  An unexpected exception fails that device only and its text is never stored (``run_per_device``).
* ``SecretManagerError`` means the connection is lost: the devices already done keep their
  result and every device not reached fails with ``remote_system_lost`` (``abort_outcomes``).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.secret_manager.exceptions import SecretManagerError
from services.secret_manager.service import SecretManagerService
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.device_runner import AbortRun, Fail, run_per_device
from workflow_steps.common.partial_outcomes import abort_outcomes
from workflow_steps.common.secret_paths import resolve_secret_paths, secret_manager_failure

logger = logging.getLogger(__name__)

# One device against the Secret Manager: (service, device, rendered path) -> device or Fail.
Operation = Callable[[SecretManagerService, DeviceContext, str], Awaitable[DeviceContext | Fail]]


@dataclass(frozen=True)
class SecretStepSpec:
    """What differs between the three steps."""

    step_id: str
    connection_id: int
    path_template: str
    strict: bool
    operation: Operation
    ok_label: str  # "found" / "written" / "generated": the summary word for the success count
    bad_label: str  # "missing" / "failed": the summary word for the failure count
    metadata: Mapping[str, Any]  # keys (without the node prefix) written next to the counts
    ok_count_key: str  # "found_count" ...
    bad_count_key: str | None  # "missing_count" ...; None when the step writes no such key


async def run_secret_step(
    spec: SecretStepSpec,
    *,
    context: WorkflowContext,
    run: WorkflowRun,
    node_id: str,
) -> list[StepOutcome]:
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{spec.step_id}: WorkflowRun has no active DB session")
    service = SecretManagerService(db)

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d",
        spec.step_id,
        context.run_id,
        node_id,
        len(context.devices),
    )

    paths, path_failures = resolve_secret_paths(
        devices=context.devices,
        path_template=spec.path_template,
        strict=spec.strict,
        run_id=context.run_id,
        node_id=node_id,
        step_id=spec.step_id,
    )

    async def work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        try:
            return await spec.operation(service, device, paths[device_id])
        except SecretManagerError as exc:
            logger.warning(
                "%s: lost connection to secret manager connection=%s: %s",
                spec.step_id,
                spec.connection_id,
                exc,
            )
            raise AbortRun(
                f"lost connection to secret manager connection {spec.connection_id}",
                secret_manager_failure(exc),
            ) from exc

    batch = await run_per_device(
        context, work, node_id=node_id, step_id=spec.step_id, concurrency=1, only=set(paths)
    )
    failed = {**path_failures, **batch.failed}
    if batch.aborted is not None:
        return abort_outcomes(
            context=context,
            node_id=node_id,
            step_id=spec.step_id,
            done_ok=batch.ok,
            done_failed=failed,
            message=batch.aborted.message,
            failure=batch.aborted.failure,
        )

    counts: dict[str, int] = {spec.ok_count_key: len(batch.ok)}
    if spec.bad_count_key is not None:
        counts[spec.bad_count_key] = len(failed)
    metadata = {
        **{f"{node_id}.{key}": value for key, value in spec.metadata.items()},
        **{f"{node_id}.{key}": value for key, value in counts.items()},
    }
    logger.info(
        "%s finished node_id=%s ok=%d failed=%d run_id=%s",
        spec.step_id,
        node_id,
        len(batch.ok),
        len(failed),
        context.run_id,
    )
    return build_outcomes(
        context,
        batch.ok,
        failed,
        metadata=metadata,
        success_summary=f"{spec.ok_label} {len(batch.ok)}, {spec.bad_label} {len(failed)}",
    )

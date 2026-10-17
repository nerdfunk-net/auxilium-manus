"""Executor for the generate-password workflow step.

Generates a random password per device (cryptographically secure, stdlib
``secrets``, never ``random``), and seals it into the device's attribute bag
for a later step in the same run (e.g. a push-config step) to use — see
doc/WORKFLOW-STEPS.md. Unlike ``secret-generate``, this step has no
dependency on the Secret Manager subsystem: generation is pure local
computation, so it needs no DB session and has no per-device or
per-connection runtime failure mode — a bad config raises before the step
does any work.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.common.attribute_write import set_device_attribute
from workflow_steps.generate_password.password_policy import PasswordPolicy, generate_password

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "generate-password"

_COUNT_FIELDS = ("min_digits", "min_uppercase", "min_lowercase", "min_special")


def _int_field(config: dict[str, Any], key: str, default: int, *, allow_negative: bool) -> int:
    raw = config.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        kind = "an integer" if allow_negative else "a non-negative integer"
        raise ValueError(f"{_STEP_ID}: {key} must be {kind}") from exc
    if not allow_negative and value < 0:
        raise ValueError(f"{_STEP_ID}: {key} must be a non-negative integer")
    return value


def _parse_config(config: dict[str, Any]) -> tuple[str, PasswordPolicy]:
    destination_path = str(config.get("destination_path") or "generated_password.value").strip()
    if not destination_path:
        raise ValueError(f"{_STEP_ID}: destination_path is required")

    length = _int_field(config, "length", 16, allow_negative=True)
    counts = {key: _int_field(config, key, 2, allow_negative=False) for key in _COUNT_FIELDS}

    try:
        policy = PasswordPolicy(length=length, **counts)
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc

    return destination_path, policy


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions

    destination_path, policy = _parse_config(config)
    del run  # no DB session needed — pure local generation

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d length=%d",
        _STEP_ID,
        context.run_id,
        node_id,
        len(context.devices),
        policy.length,
    )

    generated_devices: dict[str, DeviceContext] = {}
    generated_count = 0

    for device_id, device in context.devices.items():
        value = generate_password(policy)
        generated_devices[device_id] = set_device_attribute(
            device, destination_path, seal_secret(value)
        )
        generated_count += 1
        del value  # never referenced again — must not leak into metadata/logs

    metadata = {
        **context.metadata,
        f"{node_id}.destination_path": destination_path,
        f"{node_id}.length": policy.length,
        f"{node_id}.min_digits": policy.min_digits,
        f"{node_id}.min_uppercase": policy.min_uppercase,
        f"{node_id}.min_lowercase": policy.min_lowercase,
        f"{node_id}.min_special": policy.min_special,
        f"{node_id}.generated_count": generated_count,
    }

    logger.info(
        "%s finished node_id=%s generated=%d run_id=%s",
        _STEP_ID,
        node_id,
        generated_count,
        context.run_id,
    )

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": generated_devices, "metadata": metadata}),
            summary=f"generated {generated_count}",
        )
    ]

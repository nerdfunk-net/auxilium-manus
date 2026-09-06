"""Executor for the encrypt-attribute workflow step.

Reads a cleartext attribute value, encrypts it with a shared secret from the
credential vault, and writes the portable ciphertext token to a destination
attribute path so a later step can persist it (e.g. store-artifact -> git/disk).

Configuration errors (missing path/credential, an unknown algorithm override,
no DB session) raise and fail the step. A per-device failure — the source value
is a sealed secret, or encryption itself fails — does **not** stop the run: that
device is routed to the ``failure`` outcome carrying a ``DeviceError`` so a
downstream ``notify-on-error`` / ``notify-mattermost`` step can report it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from core.passphrase_cipher import (
    PassphraseCipherError,
    encrypt_with_passphrase,
    normalize_algorithm,
)
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.workflow_context.attribute_path import resolve_device_attribute
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER
from workflow_steps.common.attribute_write import set_device_attribute
from workflow_steps.common.credential_resolver import resolve_shared_secret_credential

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "encrypt-attribute"


def _parse_config(config: dict[str, Any]) -> tuple[str, str, str, str | None]:
    source_path = str(config.get("source_path") or "").strip()
    destination_path = str(config.get("destination_path") or "").strip()
    credential_reference = str(config.get("credential_reference") or "").strip()
    algorithm_override = str(config.get("algorithm") or "").strip() or None

    if not source_path:
        raise ValueError(f"{_STEP_ID}: source_path is required")
    if not destination_path:
        raise ValueError(f"{_STEP_ID}: destination_path is required")
    if not credential_reference:
        raise ValueError(f"{_STEP_ID}: credential_reference is required")

    return source_path, destination_path, credential_reference, algorithm_override


def _fail_device(
    *, device: DeviceContext, node_id: str, code: str, message: str
) -> DeviceContext:
    err = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
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
    del artifact_service, device_sessions

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    source_path, destination_path, credential_reference, algorithm_override = _parse_config(
        config
    )

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    cred_algorithm, passphrase = resolve_shared_secret_credential(
        db, credential_reference, acting_user_id=getattr(run, "triggered_by_id", None)
    )
    # An unknown override is a config error; normalize raises here, before the loop.
    algorithm = normalize_algorithm(algorithm_override or cred_algorithm)

    logger.info(
        "%s started run_id=%s node_id=%s algorithm=%s devices=%d",
        _STEP_ID,
        context.run_id,
        node_id,
        algorithm,
        len(context.devices),
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    encrypted_count = 0
    skipped_count = 0

    for device_id, device in context.devices.items():
        source_value = resolve_device_attribute(device, source_path, reveal_secrets=False)
        if source_value == REDACTED_PLACEHOLDER:
            failed_devices[device_id] = _fail_device(
                device=device,
                node_id=node_id,
                code="source_sealed",
                message=(
                    f"source_path {source_path!r} resolves to a sealed secret; "
                    "encrypt-attribute reads cleartext only"
                ),
            )
            continue
        if source_value is None:
            success_devices[device_id] = device
            skipped_count += 1
            continue

        try:
            token = encrypt_with_passphrase(source_value, passphrase, algorithm=algorithm)
        except PassphraseCipherError as exc:
            failed_devices[device_id] = _fail_device(
                device=device,
                node_id=node_id,
                code="encryption_failed",
                message=str(exc),
            )
            logger.warning(
                "%s encryption failed node_id=%s device=%s: %s",
                _STEP_ID,
                node_id,
                device_id,
                exc,
            )
            continue

        try:
            success_devices[device_id] = set_device_attribute(
                device, destination_path, token
            )
        except ValueError:
            # A bad destination_path is a step-wide config error, not per-device.
            raise
        except Exception as exc:
            raise RuntimeError(
                f"{_STEP_ID}: failed for device {device_id}: {exc}"
            ) from exc
        encrypted_count += 1

    failed_count = len(failed_devices)
    logger.info(
        "%s finished node_id=%s encrypted=%d skipped=%d failed=%d devices=%d",
        _STEP_ID,
        node_id,
        encrypted_count,
        skipped_count,
        failed_count,
        len(context.devices),
    )

    metadata = {
        **context.metadata,
        f"{node_id}.source_path": source_path,
        f"{node_id}.destination_path": destination_path,
        f"{node_id}.algorithm": algorithm,
        f"{node_id}.encrypted_count": encrypted_count,
        f"{node_id}.skipped_count": skipped_count,
        f"{node_id}.failed_count": failed_count,
    }

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(
                update={"devices": success_devices, "metadata": metadata}
            ),
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(
                    update={"devices": failed_devices, "metadata": metadata}
                ),
            )
        )
    return outcomes

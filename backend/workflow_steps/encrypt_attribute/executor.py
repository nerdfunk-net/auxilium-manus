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
import os
from typing import TYPE_CHECKING, Any

from core.cisco_secret import CiscoSecretError, encrypt_cisco, is_cisco_algorithm
from core.models.runs import WorkflowRun
from core.passphrase_cipher import (
    PassphraseCipherError,
    encrypt_with_passphrase,
    normalize_algorithm,
)
from models.failure import FailureInfo
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.workflow_context.attribute_path import resolve_device_attribute
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER
from workflow_steps.common.attribute_write import probe_destination_path, set_device_attribute
from workflow_steps.common.credential_resolver import resolve_shared_secret_credential
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.run_session import require_session

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "encrypt-attribute"
_DATA_FAILURE = FailureInfo(phase="internal", kind="bad_request")


def _parse_config(config: dict[str, Any]) -> tuple[str, str, str, str | None]:
    """Return ``(source_path, destination_path, credential_reference, algorithm)``."""
    source_path = str(config.get("source_path") or "").strip()
    destination_path = str(config.get("destination_path") or "").strip()
    credential_reference = str(config.get("credential_reference") or "").strip()
    algorithm_override = str(config.get("algorithm") or "").strip() or None

    if not source_path:
        raise ValueError(f"{_STEP_ID}: source_path is required")
    if not destination_path:
        raise ValueError(f"{_STEP_ID}: destination_path is required")
    # credential_reference is only needed for the keyed (AES-GCM) algorithm; the
    # Cisco formats are keyless, so that check lives in execute().

    return source_path, destination_path, credential_reference, algorithm_override


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

    source_path, destination_path, credential_reference, algorithm_override = _parse_config(config)

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    if is_cisco_algorithm(algorithm_override):
        # Keyless Cisco format: no credential, no DB session needed.
        algorithm = str(algorithm_override).strip().lower()

        def encrypt_one(value: str) -> str:
            return encrypt_cisco(value, algorithm)

    else:
        if not credential_reference:
            raise ValueError(f"{_STEP_ID}: credential_reference is required")
        db = require_session(run, _STEP_ID)

        cred_algorithm, passphrase = resolve_shared_secret_credential(
            db, credential_reference, acting_user_id=getattr(run, "triggered_by_id", None)
        )
        # An unknown override is a config error; normalize raises here, before the loop.
        algorithm = normalize_algorithm(algorithm_override or cred_algorithm)

        # One salt per execution: the key is derived once and reused for every device (each
        # value still gets its own random nonce), so 1000 devices cost one 600k-iteration KDF.
        execution_salt = os.urandom(16)

        def encrypt_one(value: str) -> str:
            return encrypt_with_passphrase(
                value, passphrase, algorithm=algorithm, salt=execution_salt
            )

    logger.info(
        "%s started run_id=%s node_id=%s algorithm=%s devices=%d",
        _STEP_ID,
        context.run_id,
        node_id,
        algorithm,
        len(context.devices),
    )

    # A destination_path that can never be written (reserved bag, bad selector shape) is a
    # step-wide config error; what depends on one device's data fails that device only.
    probe_destination_path(destination_path)
    skipped: set[str] = set()

    async def encrypt_device(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        source_value = resolve_device_attribute(device, source_path, reveal_secrets=False)
        if source_value == REDACTED_PLACEHOLDER:
            return Fail(
                "source_sealed",
                f"source_path {source_path!r} resolves to a sealed secret; "
                "encrypt-attribute reads cleartext only",
                _DATA_FAILURE,
            )
        if source_value is None:
            skipped.add(device_id)
            return device
        try:
            token = encrypt_one(source_value)
        except (PassphraseCipherError, CiscoSecretError) as exc:
            logger.warning(
                "%s encryption failed node_id=%s device=%s: %s", _STEP_ID, node_id, device_id, exc
            )
            return Fail("encryption_failed", str(exc), _DATA_FAILURE)
        return set_device_attribute(device, destination_path, token)

    batch = await run_per_device(context, encrypt_device, node_id=node_id, step_id=_STEP_ID)
    success_devices, failed_devices = batch.ok, batch.failed
    skipped_count = len(skipped)
    encrypted_count = len(success_devices) - skipped_count

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
        f"{node_id}.source_path": source_path,
        f"{node_id}.destination_path": destination_path,
        f"{node_id}.algorithm": algorithm,
        f"{node_id}.encrypted_count": encrypted_count,
        f"{node_id}.skipped_count": skipped_count,
        f"{node_id}.failed_count": failed_count,
    }

    total = len(context.devices)
    nothing_summary = (
        f"nothing to encrypt: source_path resolved on 0 of {total} devices"
        if total and skipped_count == total
        else None
    )
    return build_outcomes(
        context, success_devices, failed_devices, metadata=metadata, success_summary=nothing_summary
    )

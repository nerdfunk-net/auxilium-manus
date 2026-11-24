"""Executor for the secret-generate workflow step.

Generates a random value per device (cryptographically secure, stdlib
``secrets``), stores it at one field of an external Secret Manager
connection, and seals it into the device's attribute bag so a later step in
the same run (a push-config step) can use it — see
doc/SECRET_MANAGER_INTEGRATION.md. This is the TACACS+/SNMP rotation
primitive: the raw generated value is never returned to the run UI, never
logged, and is redacted at every persistence boundary by the existing
sealed-secret mechanism (``services.workflow_context.secret_fields``) — no
new redaction machinery is needed.

Configuration errors raise and fail the whole step. A per-device write
failure does not stop the run. A connection-wide failure
(unreachable/auth-denied) fails the whole step, matching ``secret-get``/
``secret-set``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.secret_manager.policy import SecretCharset, SecretGenerationPolicy
from services.secret_manager.service import SecretManagerService
from services.secret_manager.validation import validate_field
from services.workflow_context.device_template import parse_strict_templates
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.common.attribute_write import set_device_attribute
from workflow_steps.common.device_runner import Fail
from workflow_steps.common.secret_manager_step import SecretStepSpec, run_secret_step
from workflow_steps.common.step_flags import parse_int_flag

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "secret-generate"


def _parse_config(config: dict[str, Any]) -> tuple[int, str, str, str, SecretGenerationPolicy]:
    connection_id = config.get("connection_id")
    if not isinstance(connection_id, int):
        raise ValueError(f"{_STEP_ID}: connection_id is required")

    # Same defaults config.py declares for a freshly-dropped canvas node — a
    # node whose config was never actually edited (only displayed with an
    # illustrative default in the UI) must behave identically to one where
    # the user explicitly accepted that same value.
    path_template = str(config.get("path_template") or "network/{device.name}/tacacs").strip()
    if not path_template:
        raise ValueError(f"{_STEP_ID}: path_template is required")

    field = str(config.get("field") or "key").strip()
    if not field:
        raise ValueError(f"{_STEP_ID}: field is required")
    try:
        field = validate_field(field)
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc

    destination_path = str(config.get("destination_path") or "tacacs.shared_secret").strip()
    if not destination_path:
        raise ValueError(f"{_STEP_ID}: destination_path is required")

    raw_charset = str(config.get("charset") or "hex").strip()
    try:
        charset = SecretCharset(raw_charset)
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: unsupported charset {raw_charset!r}") from exc

    length = parse_int_flag(config, "length", default=32, minimum=-(2**31), step_id=_STEP_ID)

    try:
        policy = SecretGenerationPolicy(charset=charset, length=length)
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc

    return connection_id, path_template, field, destination_path, policy


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

    connection_id, path_template, field, destination_path, policy = _parse_config(config)
    logger.info(
        "%s policy node_id=%s charset=%s length=%d run_id=%s",
        _STEP_ID,
        node_id,
        policy.charset.value,
        policy.length,
        context.run_id,
    )

    async def generate_secret(
        service: SecretManagerService, device: DeviceContext, path: str
    ) -> DeviceContext | Fail:
        _version, value = await service.generate_field(connection_id, path, field, policy)
        updated = set_device_attribute(device, destination_path, seal_secret(value))
        del value  # never referenced again: must not leak into metadata or logs
        return updated

    spec = SecretStepSpec(
        step_id=_STEP_ID,
        connection_id=connection_id,
        path_template=path_template,
        strict=parse_strict_templates(config),
        operation=generate_secret,
        ok_label="generated",
        bad_label="failed",
        metadata={
            "path_template": path_template,
            "field": field,
            "destination_path": destination_path,
            "charset": policy.charset.value,
            "length": policy.length,
        },
        ok_count_key="generated_count",
        bad_count_key=None,
    )
    return await run_secret_step(spec, context=context, run=run, node_id=node_id)

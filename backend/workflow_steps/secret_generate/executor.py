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

from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.secret_manager.exceptions import SecretManagerError
from services.secret_manager.policy import SecretCharset, SecretGenerationPolicy
from services.secret_manager.service import SecretManagerService
from services.workflow_context.device_template import (
    TemplateRenderOptions,
    parse_strict_templates,
    render_device_template,
)
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.common.attribute_write import set_device_attribute

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "secret-generate"


def _parse_config(config: dict[str, Any]) -> tuple[int, str, str, str, SecretGenerationPolicy]:
    connection_id = config.get("connection_id")
    if not isinstance(connection_id, int):
        raise ValueError(f"{_STEP_ID}: connection_id is required")

    path_template = str(config.get("path_template") or "").strip()
    if not path_template:
        raise ValueError(f"{_STEP_ID}: path_template is required")

    field = str(config.get("field") or "").strip()
    if not field:
        raise ValueError(f"{_STEP_ID}: field is required")

    destination_path = str(config.get("destination_path") or "").strip()
    if not destination_path:
        raise ValueError(f"{_STEP_ID}: destination_path is required")

    raw_charset = str(config.get("charset") or "hex").strip()
    try:
        charset = SecretCharset(raw_charset)
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: unsupported charset {raw_charset!r}") from exc

    raw_length = config.get("length", 32)
    try:
        length = int(raw_length)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{_STEP_ID}: length must be an integer") from exc

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
    strict = parse_strict_templates(config)

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    service = SecretManagerService(db)

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d charset=%s length=%d",
        _STEP_ID,
        context.run_id,
        node_id,
        len(context.devices),
        policy.charset.value,
        policy.length,
    )

    generated_devices: dict[str, DeviceContext] = {}
    generated_count = 0

    for device_id, device in context.devices.items():
        path = render_device_template(
            path_template,
            device,
            options=TemplateRenderOptions(strict=strict, run_id=context.run_id),
        )

        try:
            _version, value = await service.generate_field(connection_id, path, field, policy)
        except SecretManagerError as exc:
            logger.warning(
                "%s: lost connection to secret manager connection=%s: %s",
                _STEP_ID,
                connection_id,
                exc,
            )
            return [
                StepOutcome(
                    name="failure",
                    context=context,
                    summary=f"could not reach secret manager connection {connection_id}: {exc}",
                )
            ]
        except ValueError:
            raise
        except Exception as exc:
            raise RuntimeError(f"{_STEP_ID}: failed for device '{device.name}': {exc}") from exc

        generated_devices[device_id] = set_device_attribute(
            device, destination_path, seal_secret(value)
        )
        generated_count += 1
        del value  # never referenced again — must not leak into metadata/logs

    metadata = {
        **context.metadata,
        f"{node_id}.path_template": path_template,
        f"{node_id}.field": field,
        f"{node_id}.destination_path": destination_path,
        f"{node_id}.charset": policy.charset.value,
        f"{node_id}.length": policy.length,
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

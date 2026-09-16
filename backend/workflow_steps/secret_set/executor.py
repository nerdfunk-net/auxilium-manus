"""Executor for the secret-set workflow step.

Writes an explicit value (a literal, or one read from another attribute path
— e.g. a static run-input the operator supplied at trigger time) to one
field of an external Secret Manager connection, per device — see
doc/SECRET_MANAGER_INTEGRATION.md. The written value is also sealed into the
device's attribute bag so later steps in the same run (a push-config step)
can use it without a second round trip to the secret manager.

Configuration errors raise and fail the whole step. A per-device write
failure does not stop the run: that device is routed to the ``failure``
outcome. A connection-wide failure (unreachable/auth-denied) fails the whole
step, matching ``secret-get``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.secret_manager.exceptions import SecretManagerError
from services.secret_manager.service import SecretManagerService
from services.workflow_context.attribute_path import resolve_device_attribute
from services.workflow_context.device_template import (
    TemplateRenderOptions,
    parse_strict_templates,
    render_device_template,
)
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER, seal_secret
from workflow_steps.common.attribute_write import set_device_attribute

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "secret-set"
_VALID_MODES = frozenset({"fixed", "attribute"})


def _parse_config(config: dict[str, Any]) -> tuple[int, str, str, str, str, str, str]:
    connection_id = config.get("connection_id")
    if not isinstance(connection_id, int):
        raise ValueError(f"{_STEP_ID}: connection_id is required")

    path_template = str(config.get("path_template") or "").strip()
    if not path_template:
        raise ValueError(f"{_STEP_ID}: path_template is required")

    field = str(config.get("field") or "").strip()
    if not field:
        raise ValueError(f"{_STEP_ID}: field is required")

    mode = str(config.get("mode") or "fixed").strip().lower()
    if mode not in _VALID_MODES:
        raise ValueError(f"{_STEP_ID}: mode must be 'fixed' or 'attribute'")

    fixed_value = str(config.get("fixed_value") or "")
    source_path = str(config.get("source_path") or "").strip()
    if mode == "fixed" and not fixed_value:
        raise ValueError(f"{_STEP_ID}: fixed_value is required in fixed mode")
    if mode == "attribute" and not source_path:
        raise ValueError(f"{_STEP_ID}: source_path is required in attribute mode")

    destination_path = str(config.get("destination_path") or "").strip()
    if not destination_path:
        raise ValueError(f"{_STEP_ID}: destination_path is required")

    return connection_id, path_template, field, mode, fixed_value, source_path, destination_path


def _fail_device(*, device: DeviceContext, node_id: str, code: str, message: str) -> DeviceContext:
    err = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )


def _resolve_value(
    *, device: DeviceContext, mode: str, fixed_value: str, source_path: str
) -> str | None:
    if mode == "fixed":
        return fixed_value
    # attribute mode is a trusted consumer — its whole purpose is pushing a
    # secret value to external storage, same as update-ise-tacacs-key.
    value = resolve_device_attribute(device, source_path, reveal_secrets=True)
    if value == REDACTED_PLACEHOLDER or value is None:
        return None
    return str(value)


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

    connection_id, path_template, field, mode, fixed_value, source_path, destination_path = (
        _parse_config(config)
    )
    strict = parse_strict_templates(config)

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    service = SecretManagerService(db)

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d",
        _STEP_ID,
        context.run_id,
        node_id,
        len(context.devices),
    )

    written_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    written_count = 0
    failed_count = 0

    for device_id, device in context.devices.items():
        value = _resolve_value(
            device=device, mode=mode, fixed_value=fixed_value, source_path=source_path
        )
        if value is None:
            failed_devices[device_id] = _fail_device(
                device=device,
                node_id=node_id,
                code="source_unresolved",
                message=f"source_path {source_path!r} resolved to no usable value",
            )
            failed_count += 1
            continue

        path = render_device_template(
            path_template,
            device,
            options=TemplateRenderOptions(strict=strict, run_id=context.run_id),
        )

        try:
            await service.set_field(connection_id, path, field, value)
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

        written_devices[device_id] = set_device_attribute(
            device, destination_path, seal_secret(value)
        )
        written_count += 1

    metadata = {
        **context.metadata,
        f"{node_id}.path_template": path_template,
        f"{node_id}.field": field,
        f"{node_id}.destination_path": destination_path,
        f"{node_id}.written_count": written_count,
        f"{node_id}.failed_count": failed_count,
    }

    logger.info(
        "%s finished node_id=%s written=%d failed=%d run_id=%s",
        _STEP_ID,
        node_id,
        written_count,
        failed_count,
        context.run_id,
    )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": written_devices, "metadata": metadata}),
            summary=f"written {written_count}, failed {failed_count}",
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

"""Executor for the secret-get workflow step.

Reads one field from an external Secret Manager connection (OpenBao or
Infisical) per device and seals it into the device's attribute bag — see
doc/SECRET_MANAGER_INTEGRATION.md. This is how a downstream step retrieves a
previously-stored (or previously-rotated) device secret, e.g. the TACACS+ key
needed to reconfigure a device.

A per-device miss (the path/field holds no value) marks that device
``DeviceStatus.FAILED`` but the step itself still emits ``"success"`` — a
"proceed with survivors" step, matching ``get-ise-tacacs-key``. The step
emits ``"failure"`` instead only when the secret manager connection itself
could not be reached or authentication failed — a condition that affects
every device equally.
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

_STEP_ID = "secret-get"


def _parse_config(config: dict[str, Any]) -> tuple[int, str, str, str, int | None]:
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

    destination_path = str(config.get("destination_path") or "tacacs.shared_secret").strip()
    if not destination_path:
        raise ValueError(f"{_STEP_ID}: destination_path is required")

    raw_version = config.get("version")
    version = int(raw_version) if isinstance(raw_version, int) else None

    return connection_id, path_template, field, destination_path, version


def _fail_device(*, device: DeviceContext, node_id: str, code: str, message: str) -> DeviceContext:
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

    connection_id, path_template, field, destination_path, version = _parse_config(config)
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

    found_devices: dict[str, DeviceContext] = {}
    missing_devices: dict[str, DeviceContext] = {}
    found_count = 0
    missing_count = 0

    for device_id, device in context.devices.items():
        path = render_device_template(
            path_template,
            device,
            options=TemplateRenderOptions(strict=strict, run_id=context.run_id),
        )

        try:
            value = await service.get_field(connection_id, path, field, version=version)
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

        if value is None:
            missing_devices[device_id] = _fail_device(
                device=device,
                node_id=node_id,
                code="secret_not_found",
                message=f"No value found at '{path}'/{field!r} for '{device.name}'",
            )
            missing_count += 1
            continue

        found_devices[device_id] = set_device_attribute(
            device, destination_path, seal_secret(value)
        )
        found_count += 1

    metadata = {
        **context.metadata,
        f"{node_id}.path_template": path_template,
        f"{node_id}.field": field,
        f"{node_id}.destination_path": destination_path,
        f"{node_id}.found_count": found_count,
        f"{node_id}.missing_count": missing_count,
    }

    logger.info(
        "%s finished node_id=%s found=%d missing=%d run_id=%s",
        _STEP_ID,
        node_id,
        found_count,
        missing_count,
        context.run_id,
    )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": found_devices, "metadata": metadata}),
            summary=f"found {found_count}, missing {missing_count}",
        )
    ]
    if missing_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(
                    update={"devices": missing_devices, "metadata": metadata}
                ),
            )
        )
    return outcomes

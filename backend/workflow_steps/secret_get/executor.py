"""Executor for the secret-get workflow step.

Reads one field from an external Secret Manager connection (OpenBao) per device and seals
it into the device's attribute bag — see doc/SECRET_MANAGER_INTEGRATION.md. This is how a
downstream step retrieves a previously-stored (or previously-rotated) device secret, e.g.
the TACACS+ key needed to reconfigure a device.

A per-device miss (the path/field holds no value, an invalid or colliding
path) marks that device ``DeviceStatus.FAILED`` and sends it through the
``failure`` outcome; the devices that were read leave through ``success``. When the
secret manager connection is lost part-way, the devices already read keep their
result and every device not yet read fails with ``remote_system_lost``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    DeviceContext,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
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
    try:
        field = validate_field(field)
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc

    destination_path = str(config.get("destination_path") or "tacacs.shared_secret").strip()
    if not destination_path:
        raise ValueError(f"{_STEP_ID}: destination_path is required")

    version: int | None = None
    if config.get("version") not in (None, ""):
        version = parse_int_flag(config, "version", default=1, minimum=1, step_id=_STEP_ID)

    return connection_id, path_template, field, destination_path, version


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

    async def read_secret(
        service: SecretManagerService, device: DeviceContext, path: str
    ) -> DeviceContext | Fail:
        value = await service.get_field(connection_id, path, field, version=version)
        if value is None:
            return Fail(
                "secret_not_found",
                f"No value found at '{path}'/{field!r} for '{device.name}'",
                FailureInfo(phase="api", kind="not_found"),
            )
        return set_device_attribute(device, destination_path, seal_secret(value))

    spec = SecretStepSpec(
        step_id=_STEP_ID,
        connection_id=connection_id,
        path_template=path_template,
        strict=parse_strict_templates(config),
        operation=read_secret,
        ok_label="found",
        bad_label="missing",
        metadata={
            "path_template": path_template,
            "field": field,
            "destination_path": destination_path,
        },
        ok_count_key="found_count",
        bad_count_key="missing_count",
    )
    return await run_secret_step(spec, context=context, run=run, node_id=node_id)

"""Executor for the secret-set workflow step.

Writes a value read from another attribute path — a run input the operator
supplied at trigger time (``run_input.<name>``), or a sealed value an
upstream secret-get / generate-password / secret-generate step produced — to
one field of an external Secret Manager connection, per device — see
doc/SECRET_MANAGER_INTEGRATION.md. The written value is also sealed into the
device's attribute bag so later steps in the same run (a push-config step)
can use it without a second round trip to the secret manager.

There is deliberately no "literal value" mode: step config is persisted in
plaintext in the workflow definition and version-controlled into the
workflows git repository, so a literal there would be a stored secret (SM3).

Configuration errors raise and fail the whole step. A per-device write
failure does not stop the run: that device is routed to the ``failure``
outcome, as does an invalid or colliding secret path. When the connection is lost
part-way, the devices already written keep their result and every device not yet
written fails with ``remote_system_lost``.
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
from services.workflow_context.attribute_path import resolve_device_attribute
from services.workflow_context.device_template import parse_strict_templates
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER, seal_secret
from workflow_steps.common.attribute_write import set_device_attribute
from workflow_steps.common.device_runner import Fail
from workflow_steps.common.secret_manager_step import SecretStepSpec, run_secret_step
from workflow_steps.secret_set.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

_STEP_ID = "secret-set"
_REMOVED_MODE_HINT = (
    "mode 'fixed' (a literal fixed_value) is no longer supported because step config "
    "is stored in plaintext in the workflow definition; supply the value as a run input "
    "and set source_path to run_input.<name>, or read it from an upstream secret step"
)


def _parse_config(config: dict[str, Any]) -> tuple[int, str, str, str, str]:
    connection_id = config.get("connection_id")
    if not isinstance(connection_id, int):
        raise ValueError(f"{_STEP_ID}: connection_id is required")

    # A saved workflow from before SM3 may still carry mode/fixed_value --
    # fail loudly with the migration hint rather than silently ignoring it.
    if str(config.get("mode") or "").strip().lower() == "fixed" or config.get("fixed_value"):
        raise ValueError(f"{_STEP_ID}: {_REMOVED_MODE_HINT}")

    # Same defaults config.py declares for a freshly-dropped canvas node — a
    # node whose config was never actually edited (only displayed with an
    # illustrative default in the UI) must behave identically to one where
    # the user explicitly accepted that same value.
    path_template = str(config.get("path_template") or get_config()["path_template"]).strip()
    if not path_template:
        raise ValueError(f"{_STEP_ID}: path_template is required")

    field = str(config.get("field") or get_config()["field"]).strip()
    if not field:
        raise ValueError(f"{_STEP_ID}: field is required")
    try:
        field = validate_field(field)
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc

    source_path = str(config.get("source_path") or get_config()["source_path"]).strip()
    if not source_path:
        raise ValueError(f"{_STEP_ID}: source_path is required")

    destination_path = str(
        config.get("destination_path") or get_config()["destination_path"]
    ).strip()
    if not destination_path:
        raise ValueError(f"{_STEP_ID}: destination_path is required")

    return connection_id, path_template, field, source_path, destination_path


def _resolve_value(*, device: DeviceContext, source_path: str) -> str | None:
    # A trusted consumer — its whole purpose is pushing a secret value to
    # external storage, same as update-ise-tacacs-key.
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

    connection_id, path_template, field, source_path, destination_path = _parse_config(config)

    async def write_secret(
        service: SecretManagerService, device: DeviceContext, path: str
    ) -> DeviceContext | Fail:
        value = _resolve_value(device=device, source_path=source_path)
        if value is None:
            return Fail(
                "source_unresolved",
                f"source_path {source_path!r} resolved to no usable value",
                FailureInfo(phase="internal", kind="bad_request"),
            )
        await service.set_field(connection_id, path, field, value)
        return set_device_attribute(device, destination_path, seal_secret(value))

    spec = SecretStepSpec(
        step_id=_STEP_ID,
        connection_id=connection_id,
        path_template=path_template,
        strict=parse_strict_templates(config),
        operation=write_secret,
        ok_label="written",
        bad_label="failed",
        metadata={
            "path_template": path_template,
            "field": field,
            "destination_path": destination_path,
        },
        ok_count_key="written_count",
        bad_count_key="failed_count",
    )
    return await run_secret_step(spec, context=context, run=run, node_id=node_id)

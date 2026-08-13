"""Executor for the get-pyats-config step.

Fetches running-config via the pyATS shim's ``POST /v1/jobs``
(``operation: "parse"``) and stores Genie's structured result into
``device.parsed``. Never imports pyats/genie directly -- see "Calling pyATS
from a step" in doc/WORKFLOW-STEPS.md. Device connection info and
credentials come entirely from the ``pyats_testbed`` bag written by an
upstream add-pyats-testbed step; this step resolves no credentials of its
own.

Startup-config is intentionally out of scope: genieparser has no registered
parser for ``show startup-config`` on any platform (confirmed against the
CiscoTestAutomation/genieparser source -- there is no ``cli_command = 'show
startup-config'`` anywhere in it, only dozens for ``show running-config``),
so requesting it via ``operation="parse"`` would fail on every device, every
time. Raw (unparsed) config capture -- running or startup -- is already
``get-device-configs``'s job (Netmiko-based); this step is Genie-structured
parsing only.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from services.pyats.credentials import PyATSCredentials
from services.pyats.source_config_service import (
    PyATSSourceConfigService,
    PyATSSourceNotFoundError,
)
from services.workflow_context.secret_fields import unwrap_secret
from workflow_steps.common.jinja_render import parse_output_key
from workflow_steps.get_pyats_config.config import get_config

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "get-pyats-config"
_RUNNING_COMMAND = "show running-config"
_COMMANDS = [_RUNNING_COMMAND]


def _resolve_source_credentials(
    db: Session, source_ids: set[str]
) -> tuple[dict[str, PyATSCredentials], dict[str, str]]:
    """Resolve every distinct pyats_source_id once. Returns (credentials_by_id, error_by_id)."""
    config_service = PyATSSourceConfigService(db)
    credentials: dict[str, PyATSCredentials] = {}
    errors: dict[str, str] = {}
    for source_id in source_ids:
        try:
            credentials[source_id] = config_service.resolve_credentials(source_id)
        except (PyATSSourceNotFoundError, PyATSValidationError) as exc:
            errors[source_id] = str(exc)
    return credentials, errors


def _fail_device(
    *, device: DeviceContext, device_id: str, node_id: str, code: str, message: str
) -> tuple[str, DeviceContext, bool]:
    err = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    failed = device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )
    return device_id, failed, False


async def _fetch_one_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    output_key: str,
    source_credentials: dict[str, PyATSCredentials],
    source_errors: dict[str, str],
) -> tuple[str, DeviceContext, bool]:
    bag = device.attribute_bags.get("pyats_testbed")
    if not isinstance(bag, dict):
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="missing_testbed",
            message="No pyats_testbed bag found -- add an Add Testbed step upstream",
        )

    source_id = str(bag.get("pyats_source_id") or "")
    if source_id in source_errors:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="source_error",
            message=source_errors[source_id],
        )
    shim_credentials = source_credentials.get(source_id)
    if shim_credentials is None:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="source_error",
            message=f"pyATS source {source_id!r} could not be resolved",
        )

    password = unwrap_secret(bag.get("password"))
    if not password:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="missing_credential",
            message="pyats_testbed bag has no usable password",
        )

    shim_device = {
        "name": device_id,
        "host": bag.get("host"),
        "os": bag.get("os"),
        "username": bag.get("username"),
        "password": password,
    }

    logger.info(
        "%s calling shim device=%s host=%s os=%s source=%s",
        _STEP_ID,
        device_id,
        bag.get("host"),
        bag.get("os"),
        source_id,
    )
    started = time.monotonic()
    try:
        shim = service_factory.get_pyats_app_service()
        response = await shim.run_job(
            shim_credentials,
            operation="parse",
            devices=[shim_device],
            commands=_COMMANDS,
        )
    except PyATSAPIError as exc:
        logger.warning(
            "%s shim call failed device=%s host=%s elapsed=%.1fs error=%s",
            _STEP_ID,
            device_id,
            bag.get("host"),
            time.monotonic() - started,
            exc,
        )
        return _fail_device(
            device=device, device_id=device_id, node_id=node_id, code="shim_error", message=str(exc)
        )

    logger.info(
        "%s shim call returned device=%s host=%s elapsed=%.1fs",
        _STEP_ID,
        device_id,
        bag.get("host"),
        time.monotonic() - started,
    )

    result = (response.get("results") or {}).get(device_id)
    if not result or not result.get("success", False):
        message = (result or {}).get("error") or "pyATS shim reported failure for this device"
        logger.warning(
            "%s device connect/parse failed device=%s host=%s error=%s",
            _STEP_ID,
            device_id,
            bag.get("host"),
            message,
        )
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="device_error",
            message=message,
        )

    commands = result.get("commands") or {}
    running_entry = commands.get(_RUNNING_COMMAND) or {}
    if running_entry.get("error"):
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="parse_failed",
            message=f"{_RUNNING_COMMAND}: {running_entry['error']}",
        )

    entry = {"running": running_entry.get("parsed")}
    parsed = dict(device.parsed)
    parsed[output_key] = entry
    enriched = device.model_copy(
        update={
            "parsed": parsed,
            "capabilities": device.capabilities | {Capability.PARSED},
            "status": DeviceStatus.OK,
        }
    )
    return device_id, enriched, True


def _partition(
    results: list[tuple[str, DeviceContext, bool]],
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext]]:
    success: dict[str, DeviceContext] = {}
    failed: dict[str, DeviceContext] = {}
    for device_id, updated_device, ok in results:
        (success if ok else failed)[device_id] = updated_device
    return success, failed


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions  # unused: no artifacts, no SSH sessions

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    output_key = parse_output_key(config.get("output_key") or get_config()["output_key"])

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d output_key=%s",
        _STEP_ID,
        run.id,
        node_id,
        len(context.devices),
        output_key,
    )

    source_ids = {
        str(device.attribute_bags["pyats_testbed"]["pyats_source_id"])
        for device in context.devices.values()
        if isinstance(device.attribute_bags.get("pyats_testbed"), dict)
        and device.attribute_bags["pyats_testbed"].get("pyats_source_id")
    }
    source_credentials, source_errors = _resolve_source_credentials(db, source_ids)

    results = await asyncio.gather(
        *[
            _fetch_one_device(
                device_id=device_id,
                device=device,
                node_id=node_id,
                output_key=output_key,
                source_credentials=source_credentials,
                source_errors=source_errors,
            )
            for device_id, device in context.devices.items()
        ]
    )
    success_devices, failed_devices = _partition(results)

    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        _STEP_ID,
        len(success_devices),
        len(failed_devices),
        run.id,
    )

    outcomes = [
        StepOutcome(name="success", context=context.model_copy(update={"devices": success_devices}))
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure", context=context.model_copy(update={"devices": failed_devices})
            )
        )
    return outcomes

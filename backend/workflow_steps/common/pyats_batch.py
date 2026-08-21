"""Shared pyATS shim batching: group devices by source, chunk, call
``run_job()`` once per chunk instead of once per device.

Used by ``get-pyats-config`` and ``get-pyats-snapshot``. Not used by
``compare-pyats-snapshot`` (calls ``/v1/diff``, not ``/v1/jobs`` -- no
subprocess/testbed involved, so batching gives no benefit) or
``configure-replace-config`` (each device already issues up to 3 sequential,
strictly-ordered ``run_job()`` calls on the same CLI session -- batching
multiple devices into one job there would require preserving that ordering
inside a shared job script, which this module does not attempt).

Device connects and command executions run **sequentially** inside a single
shim job (confirmed in ``pyats-shim/app/job_scripts/generic_script.py``:
``CommonSetup.connect_devices`` and ``RunRequestedOperation.run_commands``
both loop ``for name, device in testbed.devices.items()``, one device at a
time). Batching therefore trades "N concurrent pyATS subprocesses" for
"fewer subprocesses, each doing sequential per-device work" -- chunk size
must stay conservative, and the outer job timeout must scale with chunk
size to avoid false timeouts on otherwise-healthy chunks. See
doc/PYATS_INTEGRATION.md's "Get & Parse Config" and "Open items" sections.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from models.workflow_context import DeviceContext, DeviceError, DeviceStatus
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from services.pyats.credentials import PyATSCredentials
from services.pyats.source_config_service import (
    PyATSSourceConfigService,
    PyATSSourceNotFoundError,
)
from services.workflow_context.secret_fields import unwrap_secret

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from services.pyats.client import PyATSShimService

DEFAULT_CHUNK_SIZE = 5
BASE_TIMEOUT_SECONDS = 60.0
PER_DEVICE_TIMEOUT_SECONDS = 90.0


def resolve_source_credentials(
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
    *, device: DeviceContext, node_id: str, step_id: str, code: str, message: str
) -> DeviceContext:
    err = DeviceError(node_id=node_id, step_id=step_id, code=code, message=message)
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )


def validate_and_group_devices(
    *,
    devices: dict[str, DeviceContext],
    node_id: str,
    step_id: str,
    source_credentials: dict[str, PyATSCredentials],
    source_errors: dict[str, str],
) -> tuple[dict[str, list[tuple[str, dict[str, Any]]]], dict[str, DeviceContext]]:
    """Validate each device's ``pyats_testbed`` bag and group survivors by source.

    ``source_credentials``/``source_errors`` are the two outputs of
    ``resolve_source_credentials`` for every ``pyats_source_id`` collected
    across ``devices``. A device whose source_id has neither a resolved
    credential nor a recorded error (e.g. a missing/empty ``pyats_source_id``
    that was never attempted) is failed the same way as one with a recorded
    resolution error -- this mirrors the pre-batching per-device check.

    Returns ``(groups, failures)`` where ``groups`` maps ``pyats_source_id`` to
    a list of ``(device_id, shim_device_dict)`` (iteration order preserved for
    reproducible chunk membership), and ``failures`` maps device_id to an
    already-failed ``DeviceContext`` for devices that fail validation before
    ever reaching a shim call (missing bag, missing password, or an
    unresolvable source).
    """
    groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    failures: dict[str, DeviceContext] = {}

    for device_id, device in devices.items():
        bag = device.attribute_bags.get("pyats_testbed")
        if not isinstance(bag, dict):
            failures[device_id] = _fail_device(
                device=device,
                node_id=node_id,
                step_id=step_id,
                code="missing_testbed",
                message="No pyats_testbed bag found -- add an Add Testbed step upstream",
            )
            continue

        source_id = str(bag.get("pyats_source_id") or "")
        if source_id not in source_credentials:
            message = source_errors.get(
                source_id, f"pyATS source {source_id!r} could not be resolved"
            )
            failures[device_id] = _fail_device(
                device=device,
                node_id=node_id,
                step_id=step_id,
                code="source_error",
                message=message,
            )
            continue

        password = unwrap_secret(bag.get("password"))
        if not password:
            failures[device_id] = _fail_device(
                device=device,
                node_id=node_id,
                step_id=step_id,
                code="missing_credential",
                message="pyats_testbed bag has no usable password",
            )
            continue

        shim_device = {
            "name": device_id,
            "host": bag.get("host"),
            "os": bag.get("os"),
            "username": bag.get("username"),
            "password": password,
        }
        groups.setdefault(source_id, []).append((device_id, shim_device))

    return groups, failures


def _chunk(
    items: list[tuple[str, dict[str, Any]]], chunk_size: int
) -> list[list[tuple[str, dict[str, Any]]]]:
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


async def run_batched(
    *,
    shim: PyATSShimService,
    credentials: PyATSCredentials,
    operation: str,
    commands: list[str],
    device_group: list[tuple[str, dict[str, Any]]],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> dict[str, dict[str, Any]]:
    """Run one ``operation`` against every device in ``device_group``, chunked.

    Chunks call the shim concurrently. A chunk-level failure (network error,
    timeout, or a validation rejection) fails every device in that chunk only
    -- other chunks are unaffected. Returns a flat ``device_id -> shim result``
    dict merged across all chunks, matching the
    ``response["results"][device_id]`` shape callers already consume.
    """
    if not device_group:
        return {}

    async def _run_chunk(
        chunk: list[tuple[str, dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        shim_devices = [shim_device for _device_id, shim_device in chunk]
        timeout_seconds = BASE_TIMEOUT_SECONDS + PER_DEVICE_TIMEOUT_SECONDS * len(chunk)
        try:
            response = await shim.run_job(
                credentials,
                operation=operation,
                devices=shim_devices,
                commands=commands,
                timeout_seconds=timeout_seconds,
            )
        except (PyATSAPIError, PyATSValidationError) as exc:
            error = str(exc)
            return {
                device_id: {"success": False, "error": error, "commands": {}}
                for device_id, _shim_device in chunk
            }
        return dict(response.get("results") or {})

    chunk_results = await asyncio.gather(
        *[_run_chunk(chunk) for chunk in _chunk(device_group, chunk_size)]
    )
    merged: dict[str, dict[str, Any]] = {}
    for result in chunk_results:
        merged.update(result)
    return merged

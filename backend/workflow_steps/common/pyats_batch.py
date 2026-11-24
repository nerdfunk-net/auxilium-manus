"""Shared pyATS shim batching: group devices by source, chunk, call
``run_job()`` once per chunk instead of once per device.

Used by ``get-pyats-running-config`` and ``get-pyats-snapshot``. Not used by
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

from models.failure import FailureInfo
from models.workflow_context import DeviceContext
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from services.pyats.credentials import PyATSCredentials
from services.pyats.source_config_service import (
    PyATSSourceConfigService,
    PyATSSourceNotFoundError,
)
from services.workflow_context.secret_fields import unwrap_secret
from workflow_steps.common.device_outcomes import mark_device_failed
from workflow_steps.common.failure_records import INVALID_INPUT

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from services.pyats.client import PyATSShimService

DEFAULT_CHUNK_SIZE = 5
BASE_TIMEOUT_SECONDS = 60.0
PER_DEVICE_TIMEOUT_SECONDS = 90.0
_REQUIRED_ENTRY_FIELDS = ("host", "os", "username")


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
            failures[device_id] = mark_device_failed(
                device,
                node_id=node_id,
                step_id=step_id,
                code="missing_testbed",
                failure=INVALID_INPUT,
                message="No pyats_testbed bag found -- add an Add Testbed step upstream",
            )
            continue

        source_id = str(bag.get("pyats_source_id") or "")
        if source_id not in source_credentials:
            message = source_errors.get(
                source_id, f"pyATS source {source_id!r} could not be resolved"
            )
            failures[device_id] = mark_device_failed(
                device,
                node_id=node_id,
                step_id=step_id,
                code="source_error",
                failure=INVALID_INPUT,
                message=message,
            )
            continue

        try:
            password = unwrap_secret(bag.get("password"))
        except ValueError as exc:
            # A sealed password that cannot be decrypted (key rotated, an older seal): this
            # device cannot log in, the others can (W7-03).
            failures[device_id] = mark_device_failed(
                device,
                node_id=node_id,
                step_id=step_id,
                code="credential_unreadable",
                message=str(exc),
                failure=FailureInfo(phase="config", kind="bad_request"),
            )
            continue
        if not password:
            failures[device_id] = mark_device_failed(
                device,
                node_id=node_id,
                step_id=step_id,
                code="missing_credential",
                failure=INVALID_INPUT,
                message="pyats_testbed bag has no usable password",
            )
            continue

        # The shim builds one testbed per request and answers 400, naming no device, when any
        # entry lacks one of these: every device of the chunk would fail with that text (W7-02).
        missing = next(
            (field for field in _REQUIRED_ENTRY_FIELDS if not str(bag.get(field) or "").strip()),
            None,
        )
        if missing is not None:
            failures[device_id] = mark_device_failed(
                device,
                node_id=node_id,
                step_id=step_id,
                code=f"missing_{missing}",
                message=f"pyats_testbed bag of device {device.name!r} has no {missing}",
                failure=FailureInfo(phase="config", kind="bad_request"),
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


# A device-level error is whatever the device printed; it keeps its text, capped, because the
# operator needs it ("Authentication failed") but a banner or a dump must not fill the stored run.
MAX_SHIM_TEXT = 300
_GENERIC_DEVICE_ERROR = "pyATS shim reported failure for this device"
_DEVICE_LEVEL_FAILURE = FailureInfo(phase="command", kind="command_error")


def shim_device_failure(result: dict[str, Any] | None) -> tuple[str, FailureInfo]:
    """The message and the classification of a failed per-device shim result.

    A chunk-level failure carries the classification of its ``PyATSError`` (``run_batched``); a
    device-level error from the shim does not, and is a generic ``command_error``.
    """
    carried = (result or {}).get("failure")
    text = str((result or {}).get("error") or "").strip() or _GENERIC_DEVICE_ERROR
    if len(text) > MAX_SHIM_TEXT:
        text = f"{text[:MAX_SHIM_TEXT]}…"
    return text, carried if isinstance(carried, FailureInfo) else _DEVICE_LEVEL_FAILURE


async def shim_concurrency(shim: Any, credentials: Any, *, default: int = 4) -> int:
    """How many jobs the shim runs at once (its /health/pyats limit), so a step never makes it
    queue work for a client that may have given up (C4-01, C4R-04)."""
    try:
        limits = await shim.limits(credentials)
        return max(1, int(limits.max_concurrent_jobs))
    except Exception:  # noqa: BLE001 - advisory only
        return default


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

    gate = asyncio.Semaphore(await shim_concurrency(shim, credentials))

    async def _run_chunk(
        chunk: list[tuple[str, dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        async with gate:
            return await _run_chunk_unguarded(chunk)

    async def _run_chunk_unguarded(
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
            return dict(response.get("results") or {})
        except (PyATSAPIError, PyATSValidationError) as exc:
            error, failure = str(exc), exc.failure
        except Exception as exc:
            # A malformed answer (a proxy page instead of JSON) or any other unexpected error
            # fails this chunk only, and only its class name is kept (W7-03).
            error = type(exc).__name__
            failure = FailureInfo(
                phase="internal", kind="internal_error", exception_type=type(exc).__name__
            )
        return {
            device_id: {"success": False, "error": error, "failure": failure, "commands": {}}
            for device_id, _shim_device in chunk
        }

    chunk_results = await asyncio.gather(
        *[_run_chunk(chunk) for chunk in _chunk(device_group, chunk_size)]
    )
    merged: dict[str, dict[str, Any]] = {}
    for result in chunk_results:
        merged.update(result)
    return merged

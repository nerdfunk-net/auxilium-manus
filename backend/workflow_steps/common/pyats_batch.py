"""pyATS steps, step glue: resolve the pyATS source of each device once, validate the devices'
testbed entries and group them by source.

The chunked shim calls themselves (``run_batched``, ``shim_concurrency``) and the reading of a
per-device shim result (``shim_device_failure``) are client orchestration in
``services/pyats/batch.py``.

Used by ``get-pyats-running-config`` and ``get-pyats-snapshot`` (batched jobs);
``configure-replace-config`` and ``compare-pyats-snapshot`` use ``resolve_source_credentials``
only (their jobs are per device: up to three strictly ordered calls on one CLI session, or
``/v1/diff``, which needs no testbed).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from models.failure import FailureInfo
from models.workflow_context import DeviceContext
from services.pyats.common.exceptions import PyATSValidationError
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

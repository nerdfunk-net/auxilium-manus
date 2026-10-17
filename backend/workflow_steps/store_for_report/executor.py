"""Executor for the store-for-report step.

Appends scalar facts per device to ``report_data_records`` (history for trends); see
``ReportDataRecord``. ``mode: device`` writes one row per device (fields may count list
items); ``mode: items`` writes one row per element of a list (interfaces, NTP servers, ...).
Each device's rows are one transaction, and fan-out children and sibling branches handle
disjoint devices, so no Fan-In node is required.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import SQLAlchemyError

from core.database import get_db_session
from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.report_data.report_data_service import (
    ReportDataService,
    validate_dataset_name,
    validate_field_name,
)
from services.workflow_context.attribute_path import resolve_device_value, resolve_path_in
from services.workflow_context.secret_fields import (
    contains_sealed_secret,
    is_secret_key_name,
    path_is_known_secret,
    redact_secrets_in_data,
)
from workflow_steps.common.duplicate_keys import find_duplicate_keys

if TYPE_CHECKING:
    from services.artifacts import ArtifactService
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "store-for-report"


_MODES = frozenset({"device", "items"})
_AGGREGATES = frozenset({"", "count"})
# Field path meaning "the list item itself" in items mode (for lists of plain values).
_ITEM_SELF_PATH = "."


@dataclass(frozen=True)
class FieldSpec:
    name: str
    attribute_path: str
    aggregate: str = ""
    where_field: str = ""
    where_equals: str | None = None


def _parse_mode(config: dict[str, Any]) -> str:
    mode = str(config.get("mode") or "device").strip().lower()
    if mode not in _MODES:
        raise ValueError(f"{_STEP_ID}: mode must be one of {sorted(_MODES)}")
    return mode


def _parse_field(entry: Any, *, mode: str) -> FieldSpec:
    if not isinstance(entry, dict):
        raise ValueError(f"{_STEP_ID}: each field must have a name and an attribute_path")
    name = str(entry.get("name") or "").strip()
    path = str(entry.get("attribute_path") or "").strip()
    try:
        validate_field_name(name)
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc
    if not path:
        raise ValueError(f"{_STEP_ID}: field {name!r} needs an attribute_path")

    aggregate = str(entry.get("aggregate") or "").strip().lower()
    if aggregate not in _AGGREGATES:
        raise ValueError(f"{_STEP_ID}: field {name!r}: aggregate must be empty or 'count'")
    where_field = str(entry.get("where_field") or "").strip()
    where_equals = entry.get("where_equals")
    if aggregate and mode == "items":
        raise ValueError(f"{_STEP_ID}: field {name!r}: aggregate is only available in device mode")
    if where_field and aggregate != "count":
        raise ValueError(f"{_STEP_ID}: field {name!r}: where needs aggregate 'count'")
    if where_field and not isinstance(where_equals, str):
        raise ValueError(f"{_STEP_ID}: field {name!r}: where_field needs where_equals")
    if not aggregate:
        _reject_secret_shaped(name, path)
    return FieldSpec(
        name=name,
        attribute_path=path,
        aggregate=aggregate,
        where_field=where_field,
        where_equals=where_equals if where_field else None,
    )


_PATH_BRACKETS = re.compile(r"\[[^\]]*\]")


def _reject_secret_shaped(name: str, path: str) -> None:
    """Fail the configuration when a stored field is named like, or read from, a secret.

    ``report_data_records`` is append-only, so a plaintext secret must never reach it.
    The check is on names (``password``, ``community``, ``*_secret``, ...) and on the
    known secret bag paths, the same rules the other persistence paths use. A count
    stores only a number and is exempt.
    """
    segments = [_PATH_BRACKETS.sub("", part) for part in path.split(".") if part]
    if (
        is_secret_key_name(name)
        or any(is_secret_key_name(segment) for segment in segments)
        or path_is_known_secret(".".join(segments))
    ):
        raise ValueError(
            f"{_STEP_ID}: field {name!r} (attribute_path {path!r}) looks like a secret "
            "(password, community, token, ...) and cannot be stored for reports"
        )


def _parse_fields(config: dict[str, Any], *, mode: str) -> list[FieldSpec]:
    raw = config.get("fields")
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{_STEP_ID}: fields must be a non-empty list")
    parsed: list[FieldSpec] = []
    seen: set[str] = set()
    for entry in raw:
        spec = _parse_field(entry, mode=mode)
        if spec.name in seen:
            raise ValueError(f"{_STEP_ID}: duplicate field name {spec.name!r}")
        seen.add(spec.name)
        parsed.append(spec)
    return parsed


def _parse_items_path(config: dict[str, Any], *, mode: str) -> str:
    path = str(config.get("items_path") or "").strip()
    if mode == "items" and not path:
        raise ValueError(f"{_STEP_ID}: items_path is required when mode is 'items'")
    return path


def _parse_dataset(config: dict[str, Any]) -> str:
    try:
        return validate_dataset_name(str(config.get("dataset") or ""))
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc


def _as_text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _count(value: Any, spec: FieldSpec) -> int | None:
    """Count the items of the list at the path, or only those whose ``where_field`` equals
    ``where_equals`` (compared as text; booleans as ``true``/``false``). A missing path is
    unknown (``None``), an empty list is 0."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(
            f"field {spec.name!r} (attribute_path {spec.attribute_path!r}): count needs a "
            f"list, got {type(value).__name__}"
        )
    if not spec.where_field:
        return len(value)
    return sum(
        1
        for item in value
        if isinstance(item, dict)
        and _as_text(resolve_path_in(item, spec.where_field)) == spec.where_equals
    )


def _holds_secret(value: Any) -> bool:
    """A sealed envelope, or text containing a cleartext secret this run has handled."""
    if contains_sealed_secret(value):
        return True
    return isinstance(value, str) and redact_secrets_in_data(value) != value


def _reject_secret(value: Any, spec: FieldSpec) -> None:
    if _holds_secret(value):
        raise ValueError(
            f"field {spec.name!r} (attribute_path {spec.attribute_path!r}) resolves to a "
            "secret-valued attribute, which cannot be stored for reports"
        )


def _collect_fields(
    device: DeviceContext, fields: list[FieldSpec], *, run_id: str
) -> dict[str, Any]:
    """Resolve every mapped path; a missing path yields ``None``, a secret fails the device.

    A count only exposes a number, so secrets elsewhere in the counted list do not matter.
    """
    collected: dict[str, Any] = {}
    for spec in fields:
        value = resolve_device_value(device, spec.attribute_path, run_id=run_id)
        if spec.aggregate == "count":
            collected[spec.name] = _count(value, spec)
            continue
        _reject_secret(value, spec)
        collected[spec.name] = value
    return collected


def _collect_items(
    device: DeviceContext, items_path: str, fields: list[FieldSpec], *, run_id: str
) -> list[dict[str, Any]]:
    """One dict per list element at *items_path*, with the fields read relative to it."""
    raw = resolve_device_value(device, items_path, run_id=run_id)
    if raw is None:
        raise ValueError(f"items_path {items_path!r} resolved to nothing")
    if not isinstance(raw, list):
        raise ValueError(
            f"items_path {items_path!r} must resolve to a list, got {type(raw).__name__}"
        )
    items: list[dict[str, Any]] = []
    for element in raw:
        item: dict[str, Any] = {}
        for spec in fields:
            if spec.attribute_path == _ITEM_SELF_PATH:
                value = element
            else:
                value = resolve_path_in(element, spec.attribute_path)
            _reject_secret(value, spec)
            item[spec.name] = value
        items.append(item)
    return items


def _empty_fields_summary(
    fields: list[FieldSpec], fields_with_a_value: set[str], stored_devices: int
) -> str | None:
    """Name the fields that were empty for every stored device (O4-05).

    A path that matches nothing is valid syntax and stores ``null``, which is right for an
    optional attribute but also what a mistyped path does. The step stays green; this tells the
    user which fields to check. Field names only, never values."""
    if stored_devices == 0:
        return None
    empty = [spec.name for spec in fields if spec.name not in fields_with_a_value]
    if not empty:
        return None
    names = ", ".join(repr(name) for name in empty)
    return (
        f"field(s) {names} had no value for any of {stored_devices} device(s); "
        "check the attribute path"
    )


# What the assistant may see without the content opt-in (models/failure.py): a closed vocabulary.
# A value or path that cannot be stored (or a duplicate device name) is a problem with the input;
# anything else is a bug or a database fault, of which only the exception class is kept.
_INPUT_FAILURE = FailureInfo(phase="config", kind="bad_request")


def _internal_failure(exc: BaseException) -> FailureInfo:
    return FailureInfo(phase="internal", kind="internal_error", exception_type=type(exc).__name__)


def _device_failure(
    *,
    device: DeviceContext,
    node_id: str,
    code: str,
    message: str,
    failure: FailureInfo | None = None,
) -> DeviceContext:
    err = DeviceError(
        node_id=node_id, step_id=_STEP_ID, code=code, message=message, failure=failure
    )
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

    dataset = _parse_dataset(config)
    mode = _parse_mode(config)
    fields = _parse_fields(config, mode=mode)
    items_path = _parse_items_path(config, mode=mode)

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    logger.info(
        "store-for-report started run_id=%s node_id=%s devices=%d dataset=%s",
        run.id,
        node_id,
        len(context.devices),
        dataset,
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    fields_with_a_value: set[str] = set()
    db = get_db_session()
    try:
        service = ReportDataService(db)
        duplicates = find_duplicate_keys(
            (device_id, device.name) for device_id, device in context.devices.items()
        )
        for device_id, device in context.devices.items():
            if device_id in duplicates:
                # Rows are keyed by (run, dataset, device name): a second device with the
                # same name would silently overwrite the first one's row.
                failed_devices[device_id] = _device_failure(
                    device=device,
                    node_id=node_id,
                    code="duplicate_device_name",
                    message=f"duplicate device name {device.name!r} in this step; "
                    "report rows are keyed by device name",
                    failure=_INPUT_FAILURE,
                )
                continue
            try:
                if mode == "items":
                    service.record_device_items(
                        device_name=device.name,
                        dataset=dataset,
                        items=_collect_items(device, items_path, fields, run_id=context.run_id),
                        run_id=run.id,
                        node_id=node_id,
                        field_names=[spec.name for spec in fields],
                    )
                else:
                    data = _collect_fields(device, fields, run_id=context.run_id)
                    service.record_device_data(
                        device_name=device.name,
                        dataset=dataset,
                        data=data,
                        run_id=run.id,
                        node_id=node_id,
                    )
                    fields_with_a_value.update(
                        name for name, value in data.items() if value is not None
                    )
                success_devices[device_id] = device.model_copy(update={"status": DeviceStatus.OK})
            except SQLAlchemyError as exc:
                # The driver message embeds the SQL and the bound values, so it is not logged:
                # only the error class and the database's SQLSTATE are.
                logger.error(
                    "store-for-report database error run_id=%s node_id=%s device=%s "
                    "error=%s sqlstate=%s",
                    run.id,
                    node_id,
                    device.name,
                    type(exc).__name__,
                    getattr(getattr(exc, "orig", None), "sqlstate", None),
                )
                failed_devices[device_id] = _device_failure(
                    device=device,
                    node_id=node_id,
                    code=type(exc).__name__.lower(),
                    message="database error while storing report data",
                    failure=_internal_failure(exc),
                )
            except ValueError as exc:
                # Expected per-device failures (bad value, secret, missing list). The message
                # names fields and paths, never values.
                logger.warning(
                    "store-for-report device failed run_id=%s node_id=%s device=%s: %s",
                    run.id,
                    node_id,
                    device.name,
                    exc,
                )
                failed_devices[device_id] = _device_failure(
                    device=device,
                    node_id=node_id,
                    code=type(exc).__name__.lower(),
                    message=str(exc),
                    failure=_INPUT_FAILURE,
                )
            except Exception as exc:
                # Not an input problem: a bug or an environment fault. The traceback stays in the
                # backend log; the run result gets a fixed sentence, because the exception text
                # can hold paths and values (like the database branch above).
                logger.exception(
                    "store-for-report unexpected error run_id=%s node_id=%s device=%s",
                    run.id,
                    node_id,
                    device.name,
                )
                failed_devices[device_id] = _device_failure(
                    device=device,
                    node_id=node_id,
                    code=type(exc).__name__.lower(),
                    message="unexpected error while storing report data",
                    failure=_internal_failure(exc),
                )
    finally:
        db.close()

    logger.info(
        "store-for-report finished success=%d failure=%d run_id=%s",
        len(success_devices),
        len(failed_devices),
        run.id,
    )

    summary = None
    if mode == "device":
        summary = _empty_fields_summary(fields, fields_with_a_value, len(success_devices))
    if summary:
        logger.warning(
            "store-for-report %s run_id=%s node_id=%s dataset=%s", summary, run.id, node_id, dataset
        )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
            summary=summary,
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure", context=context.model_copy(update={"devices": failed_devices})
            )
        )
    return outcomes

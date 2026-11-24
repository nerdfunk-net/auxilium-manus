"""Executor for the enrich-attributes step.

Reads a CSV lookup table (export directory or Git repository). One column is the
key; a device is matched when its own attribute (``device_attribute_path``) equals
(or contains) the row's key. The other columns of the first matching row are
deep-merged into the device's attribute bag at ``destination_path``.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.csv_lookup import (
    MAX_FILE_BYTES,
    CsvLookupError,
    CsvRow,
    RowIndex,
    parse_csv_rows,
    parse_delimiter,
)
from services.git.paths import is_contained_regular_file, resolve_within_repo
from services.workflow_context.attribute_path import resolve_device_attribute
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER, is_sealed_secret
from workflow_steps.common.attribute_merge import (
    merge_into_device_attribute,
    validate_merge_destination,
)
from workflow_steps.common.file_source_root import resolve_source_root
from workflow_steps.common.git_repository_loader import parse_repository_id
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.step_flags import parse_bool_flag

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "enrich-attributes"
_SOURCES = frozenset({"filesystem", "git"})
_MATCH_MODES = frozenset({"match", "contains"})
# The registry and get_config() advertise this default; validation accepts a blank field.
_DEFAULT_DESTINATION = "data"


@dataclass(frozen=True)
class _Parsed:
    source: str
    git_repository_id: int | None
    path: str
    delimiter: str
    key_column: str
    device_attribute_path: str
    match_mode: str
    case_insensitive: bool
    destination_path: str
    overwrite: bool


def _delimiter(raw: Any) -> str:
    try:
        return parse_delimiter(raw)
    except CsvLookupError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc


def _parse_config(config: dict[str, Any]) -> _Parsed:
    source = str(config.get("source") or "filesystem").strip().lower()
    if source not in _SOURCES:
        raise ValueError(f"{_STEP_ID}: source must be one of {sorted(_SOURCES)}")

    git_repository_id = parse_repository_id(config.get("git_repository_id"), step_id=_STEP_ID)
    if source == "git" and git_repository_id is None:
        raise ValueError(f"{_STEP_ID}: git_repository_id is required when source=git")

    path = str(config.get("path") or "").strip()
    if not path:
        raise ValueError(f"{_STEP_ID}: path is required")

    key_column = str(config.get("key_column") or "").strip()
    if not key_column:
        raise ValueError(f"{_STEP_ID}: key_column is required")

    device_attribute_path = str(config.get("device_attribute_path") or "").strip()
    if not device_attribute_path:
        raise ValueError(f"{_STEP_ID}: device_attribute_path is required")

    match_mode = str(config.get("match_mode") or "match").strip().lower()
    if match_mode not in _MATCH_MODES:
        raise ValueError(f"{_STEP_ID}: match_mode must be one of {sorted(_MATCH_MODES)}")

    destination_path = str(config.get("destination_path") or "").strip() or _DEFAULT_DESTINATION
    try:
        validate_merge_destination(destination_path)
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc

    return _Parsed(
        source=source,
        git_repository_id=git_repository_id,
        path=path,
        delimiter=_delimiter(config.get("delimiter")),
        key_column=key_column,
        device_attribute_path=device_attribute_path,
        match_mode=match_mode,
        case_insensitive=parse_bool_flag(config, "case_insensitive"),
        destination_path=destination_path,
        overwrite=parse_bool_flag(config, "overwrite"),
    )


def _fail_device(
    *,
    device: DeviceContext,
    node_id: str,
    code: str,
    message: str,
    failure: FailureInfo,
) -> DeviceContext:
    err = DeviceError(
        node_id=node_id, step_id=_STEP_ID, code=code, message=message, failure=failure
    )
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )


def _sealed_conflict(
    device: DeviceContext, destination_path: str, values: dict[str, str]
) -> str | None:
    """Name the sealed secret a merge would overwrite or extend, if there is one.

    The merge helper replaces any non-mapping leaf (and merges into a mapping, which a sealed
    envelope is), so a CSV column must never land on or inside a sealed value, whatever
    ``overwrite`` says.
    """
    bag_name, remainder = validate_merge_destination(destination_path)
    node: Any = device.attribute_bags.get(bag_name, {})
    walked = bag_name
    for part in [p for p in remainder.split(".") if p]:
        if is_sealed_secret(node):
            return walked
        if not isinstance(node, dict):
            return None
        node = node.get(part)
        walked = f"{walked}.{part}"
    if is_sealed_secret(node):
        return walked
    if isinstance(node, dict):
        for column in values:
            if is_sealed_secret(node.get(column)):
                return f"{walked}.{column}"
    return None


def _is_regular_file(root: Path, relative: str) -> bool:
    return is_contained_regular_file(root, Path(root).resolve() / relative)


async def _load_rows(parsed: _Parsed, config: dict[str, Any]) -> list[CsvRow]:
    async with AsyncExitStack() as stack:
        root = await resolve_source_root(
            source=parsed.source,
            git_repository_id=parsed.git_repository_id,
            stack=stack,
            allow_stale=parse_bool_flag(config, "allow_stale_repository"),
            # DELIBERATE, do not "fix" by defaulting to a pull: off by default, also for stored
            # steps without the key. A Pull Git step refreshes the repository once; every (fan-out)
            # child only reads it, so it holds the git lock for milliseconds. A pull or a git
            # status check per device is what timed out ("Timed out after 90s waiting for the
            # lock"). The read says which commit it read (run event). See doc/WORKFLOW-STEPS.md.
            refresh=parse_bool_flag(config, "refresh_repository"),
            step_id=_STEP_ID,
        )

        target = resolve_within_repo(root, parsed.path)
        if not await asyncio.to_thread(_is_regular_file, root, parsed.path):
            # Also reached for a symlink: the hardened repository readers never follow one.
            raise FileNotFoundError(f"{_STEP_ID}: file not found: {parsed.path}")
        if (await asyncio.to_thread(target.stat)).st_size > MAX_FILE_BYTES:
            raise ValueError(f"{_STEP_ID}: {parsed.path} is larger than {MAX_FILE_BYTES} bytes")
        text = await asyncio.to_thread(target.read_text, encoding="utf-8")
    try:
        return parse_csv_rows(
            text,
            key_column=parsed.key_column,
            delimiter=parsed.delimiter,
            label=parsed.path,
        )
    except CsvLookupError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del device_sessions  # unused: this step never connects to a device
    del artifact_service  # unused: rows are merged into the bag, not stored

    parsed = _parse_config(config)
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    rows = await _load_rows(parsed, config)
    index = RowIndex(
        rows,
        contains=parsed.match_mode == "contains",
        case_insensitive=parsed.case_insensitive,
    )
    if index.duplicates and parsed.match_mode == "match":
        logger.warning(
            "enrich-attributes duplicate keys run_id=%s node_id=%s duplicates=%d (first row wins)",
            log_run_id(run),
            node_id,
            index.duplicates,
        )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    matched = unmatched = 0
    for device_id, device in context.devices.items():
        # Never decrypt a sealed leaf for a comparison: it resolves to the placeholder, which is
        # treated like "no value" so every sealed device does not match one shared row.
        value = resolve_device_attribute(device, parsed.device_attribute_path, reveal_secrets=False)
        key = value.strip() if value and value != REDACTED_PLACEHOLDER else ""
        row = index.find(key) if key else None
        if row is None:
            unmatched += 1
            success_devices[device_id] = device
            continue
        conflict = _sealed_conflict(device, parsed.destination_path, row.values)
        if conflict is not None:
            failed_devices[device_id] = _fail_device(
                device=device,
                node_id=node_id,
                code="sealed_secret_conflict",
                message=f"{conflict} holds a sealed secret; it is not overwritten by a CSV value",
                failure=FailureInfo(phase="internal", kind="bad_request"),
            )
            continue
        try:
            success_devices[device_id] = merge_into_device_attribute(
                device, parsed.destination_path, row.values, overwrite=parsed.overwrite
            )
            matched += 1
        except Exception as exc:  # defensive: destination shape is pre-validated
            failed_devices[device_id] = _fail_device(
                device=device,
                node_id=node_id,
                code=type(exc).__name__.lower(),
                message=str(exc),
                failure=FailureInfo(
                    phase="internal", kind="internal_error", exception_type=type(exc).__name__
                ),
            )

    logger.info(
        "enrich-attributes finished run_id=%s node_id=%s matched=%d unmatched=%d failed=%d rows=%d",
        log_run_id(run),
        node_id,
        matched,
        unmatched,
        len(failed_devices),
        len(rows),
    )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed_devices}),
            )
        )
    return outcomes

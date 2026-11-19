"""Executor for the enrich-attributes step.

Reads a CSV lookup table (export directory or Git repository). One column is the
key; a device is matched when its own attribute (``device_attribute_path``) equals
(or contains) the row's key. The other columns of the first matching row are
deep-merged into the device's attribute bag at ``destination_path``.
"""

from __future__ import annotations

import asyncio
import csv
import io
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
from services.git.paths import is_contained_regular_file, resolve_within_repo
from services.workflow_context.attribute_path import resolve_device_attribute
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER, is_sealed_secret
from workflow_steps.common.attribute_merge import (
    merge_into_device_attribute,
    validate_merge_destination,
)
from workflow_steps.common.file_source_root import resolve_source_root
from workflow_steps.common.step_flags import parse_bool_flag

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "enrich-attributes"
_SOURCES = frozenset({"filesystem", "git"})
_MATCH_MODES = frozenset({"match", "contains"})
_MAX_FILE_BYTES = 10 * 1024 * 1024
_MAX_ROWS = 200_000
_DELIMITER_WORDS = {"tab": "\t", "\\t": "\t"}
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


@dataclass(frozen=True)
class _Row:
    key: str
    values: dict[str, str]


def _parse_delimiter(raw: Any) -> str:
    text = ";" if raw is None or raw == "" else str(raw)
    text = _DELIMITER_WORDS.get(text.strip().lower(), text)
    if len(text) != 1:
        raise ValueError(f"{_STEP_ID}: delimiter must be a single character (or 'tab')")
    return text


def _parse_repository_id(raw: Any) -> int | None:
    """A whole number (or its decimal text); ``True`` / ``7.9`` must not pick another repository."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool) or (isinstance(raw, float) and not raw.is_integer()):
        raise ValueError(f"{_STEP_ID}: git_repository_id must be a whole number")
    try:
        return int(raw)
    except TypeError, ValueError:
        raise ValueError(f"{_STEP_ID}: git_repository_id must be a whole number") from None


def _parse_config(config: dict[str, Any]) -> _Parsed:
    source = str(config.get("source") or "filesystem").strip().lower()
    if source not in _SOURCES:
        raise ValueError(f"{_STEP_ID}: source must be one of {sorted(_SOURCES)}")

    git_repository_id = _parse_repository_id(config.get("git_repository_id"))
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
        delimiter=_parse_delimiter(config.get("delimiter")),
        key_column=key_column,
        device_attribute_path=device_attribute_path,
        match_mode=match_mode,
        case_insensitive=parse_bool_flag(config, "case_insensitive"),
        destination_path=destination_path,
        overwrite=parse_bool_flag(config, "overwrite"),
    )


def _normalize(value: str, *, case_insensitive: bool) -> str:
    return value.casefold() if case_insensitive else value


def parse_csv_rows(text: str, parsed: _Parsed) -> list[_Row]:
    """Parse *text* into rows keyed by ``parsed.key_column`` (values trimmed strings)."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿"), newline=""), delimiter=parsed.delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError(f"{_STEP_ID}: {parsed.path} is empty") from None
    except csv.Error as exc:
        raise ValueError(f"{_STEP_ID}: invalid CSV: {exc}") from exc

    columns = [name.strip() for name in header]
    if len(set(columns)) != len(columns):
        raise ValueError(f"{_STEP_ID}: duplicate column names in the CSV header")
    if parsed.key_column not in columns:
        raise ValueError(
            f"{_STEP_ID}: key column {parsed.key_column!r} not found in header {columns}"
        )
    key_index = columns.index(parsed.key_column)

    rows: list[_Row] = []
    try:
        for record in reader:
            if not any(cell.strip() for cell in record):
                continue  # blank line
            if len(rows) >= _MAX_ROWS:
                raise ValueError(f"{_STEP_ID}: more than {_MAX_ROWS} rows in {parsed.path}")
            cells = [cell.strip() for cell in record]
            cells += [""] * (len(columns) - len(cells))
            # An empty cell adds nothing: with overwrite off, an "" key would block a real value.
            values = {
                name: cells[i]
                for i, name in enumerate(columns)
                if i != key_index and name and cells[i]
            }
            rows.append(_Row(key=cells[key_index], values=values))
    except csv.Error as exc:
        raise ValueError(f"{_STEP_ID}: invalid CSV: {exc}") from exc
    return rows


class _RowIndex:
    """First-match lookup: dict for ``match``, ordered scan for ``contains``."""

    def __init__(self, rows: list[_Row], parsed: _Parsed) -> None:
        self._contains = parsed.match_mode == "contains"
        self._ci = parsed.case_insensitive
        self._ordered: list[tuple[str, _Row]] = []
        self._exact: dict[str, _Row] = {}
        self.duplicates = 0
        for row in rows:
            if not row.key:
                continue
            key = _normalize(row.key, case_insensitive=self._ci)
            self._ordered.append((key, row))
            if key in self._exact:
                self.duplicates += 1
            else:
                self._exact[key] = row

    def find(self, device_value: str) -> _Row | None:
        """The first matching row in file order (``contains`` stops at the first hit)."""
        value = _normalize(device_value, case_insensitive=self._ci)
        if not self._contains:
            return self._exact.get(value)
        return next((row for key, row in self._ordered if key in value), None)


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


async def _load_rows(parsed: _Parsed, config: dict[str, Any]) -> list[_Row]:
    async with AsyncExitStack() as stack:
        root = await resolve_source_root(
            source=parsed.source,
            git_repository_id=parsed.git_repository_id,
            stack=stack,
            allow_stale=parse_bool_flag(config, "allow_stale_repository"),
            step_id=_STEP_ID,
        )

        target = resolve_within_repo(root, parsed.path)
        if not await asyncio.to_thread(_is_regular_file, root, parsed.path):
            # Also reached for a symlink: the hardened repository readers never follow one.
            raise FileNotFoundError(f"{_STEP_ID}: file not found: {parsed.path}")
        if (await asyncio.to_thread(target.stat)).st_size > _MAX_FILE_BYTES:
            raise ValueError(f"{_STEP_ID}: {parsed.path} is larger than {_MAX_FILE_BYTES} bytes")
        text = await asyncio.to_thread(target.read_text, encoding="utf-8")
    return parse_csv_rows(text, parsed)


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
    index = _RowIndex(rows, parsed)
    if index.duplicates and parsed.match_mode == "match":
        logger.warning(
            "enrich-attributes duplicate keys run_id=%s node_id=%s duplicates=%d (first row wins)",
            run.id,
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
        run.id,
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

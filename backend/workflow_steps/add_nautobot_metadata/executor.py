"""Executor for the add-nautobot-metadata workflow step.

Ensures Nautobot reference data (a Location or a Device Type) exists for each
device. Every config value is a fixed string or contains ``{path}`` attribute-bag
tokens, resolved per device. Creation is get-or-create: an existing object is
reused. Devices that resolve to the same object share a single Nautobot call.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.metadata_creation import (
    MetadataCreationService,
    MetadataReferenceNotFoundError,
)
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.update_field_expression import resolve_template_if_present

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "add-nautobot-metadata"
_DEFAULT_STATUS = "Active"
_DEFAULT_HEIGHT = "1"

_LOCATION = "location"
_DEVICE_TYPE = "device_type"
_METADATA_TYPES = frozenset({_LOCATION, _DEVICE_TYPE})

# Field -> (required, lenient). A lenient field (description) treats an unresolvable
# ``{path}`` token as empty instead of failing the device; every other field fails on it
# (use ``{path | default('')}`` to make one optional).
_FIELDS: dict[str, dict[str, tuple[bool, bool]]] = {
    _LOCATION: {
        "location_type": (True, False),
        "name": (True, False),
        "status": (True, False),
        "description": (False, True),
        "parent": (False, False),
    },
    _DEVICE_TYPE: {
        "manufacturer": (True, False),
        "role": (True, False),
        "model": (True, False),
        "height": (True, False),
        "platform": (False, False),
    },
}
_FIELD_DEFAULTS = {"status": _DEFAULT_STATUS, "height": _DEFAULT_HEIGHT}

_Ensure = Callable[[MetadataCreationService, dict[str, Any]], Awaitable[dict[str, Any]]]


class _DeviceFailure(Exception):
    """A per-device problem that routes the device to the failure outcome."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    metadata_type: str
    raw_fields: dict[str, str]


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    source_id = str(config.get("nautobot_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is not configured")

    metadata_type = str(config.get("metadata_type") or _LOCATION).strip().lower()
    if metadata_type not in _METADATA_TYPES:
        raise ValueError(
            f"{_STEP_ID}: metadata_type must be one of {sorted(_METADATA_TYPES)}, "
            f"got {metadata_type!r}"
        )

    section = config.get(metadata_type) or {}
    if not isinstance(section, dict):
        raise ValueError(f"{_STEP_ID}: {metadata_type} must be an object")
    raw_fields = {key: str(section.get(key) or "").strip() for key in _FIELDS[metadata_type]}
    return _ParsedConfig(source_id=source_id, metadata_type=metadata_type, raw_fields=raw_fields)


def _resolve_fields(device: DeviceContext, parsed: _ParsedConfig) -> dict[str, Any]:
    """Resolve every field for one device; raise ``_DeviceFailure`` when it cannot be."""
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for key, (required, lenient) in _FIELDS[parsed.metadata_type].items():
        raw = parsed.raw_fields[key] or _FIELD_DEFAULTS.get(key, "")
        value, unresolved = resolve_template_if_present(device=device, raw_value=raw)
        if unresolved is not None:
            if not lenient:
                raise _DeviceFailure(
                    "unresolved_attribute",
                    f"{key}: attribute {unresolved} is not available on this device",
                )
            value = ""
        value = (value or "").strip()
        if required and not value:
            value = _FIELD_DEFAULTS.get(key, "")
        if required and not value:
            missing.append(key)
        resolved[key] = value
    if missing:
        raise _DeviceFailure(
            "missing_required_field",
            f"Required field(s) resolved to an empty value: {', '.join(missing)}",
        )
    return resolved


def _parse_height(text: str) -> int:
    try:
        height = int(text)
    except ValueError:
        height = 0
    if height < 1:
        raise _DeviceFailure(
            "invalid_height", f"height must be a positive whole number, got {text!r}"
        )
    return height


async def _ensure_location(service: MetadataCreationService, v: dict[str, Any]) -> dict[str, Any]:
    result = await service.ensure_location(
        location_type=v["location_type"],
        name=v["name"],
        status=v["status"],
        description=v["description"],
        parent=v["parent"] or None,
    )
    # {name, id} dicts, the shape Get Nautobot Attributes writes, so {nautobot.location.name}
    # / {nautobot.location.id} keep resolving after this step.
    return {"location": {"name": result.name, "id": result.id}}


async def _ensure_device_type(
    service: MetadataCreationService, v: dict[str, Any]
) -> dict[str, Any]:
    result = await service.ensure_device_type(
        manufacturer=v["manufacturer"],
        model=v["model"],
        height=v["height"],
        role=v["role"],
        platform=v["platform"] or None,
    )
    bag_updates: dict[str, Any] = {
        "device_type": {"model": result.model, "id": result.id},
        "role": {"name": result.role, "id": result.role_id},
    }
    if result.platform:
        bag_updates["platform"] = {"name": result.platform, "id": result.platform_id}
    return bag_updates


_ENSURERS: dict[str, _Ensure] = {_LOCATION: _ensure_location, _DEVICE_TYPE: _ensure_device_type}


_IDENTITY_FIELDS = {
    _LOCATION: ("location_type", "name", "parent"),
    _DEVICE_TYPE: ("manufacturer", "model"),
}


def _identity_key(metadata_type: str, values: dict[str, Any]) -> tuple[Any, ...]:
    """Key a call by what identifies the object (case-insensitive, as Nautobot lookups are
    here), not by attributes like description/height, so devices wanting the same object
    never race each other and the first caller's attributes win deterministically."""
    return (metadata_type, *(str(values[f]).lower() for f in _IDENTITY_FIELDS[metadata_type]))


class _SharedCalls:
    """Run each distinct ensure call once; devices resolving to the same key await it."""

    def __init__(self) -> None:
        self._tasks: dict[tuple[Any, ...], asyncio.Task[dict[str, Any]]] = {}

    async def run(
        self, key: tuple[Any, ...], factory: Callable[[], Awaitable[dict[str, Any]]]
    ) -> dict[str, Any]:
        task = self._tasks.get(key)
        if task is None:
            task = asyncio.ensure_future(factory())
            self._tasks[key] = task
        return await task


def _fail(device: DeviceContext, node_id: str, code: str, message: str) -> DeviceContext:
    error = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, error]}
    )


def _enrich(device: DeviceContext, bag_updates: dict[str, Any]) -> DeviceContext:
    # Merge into (never replace) the existing nautobot bag so attributes read by an
    # upstream step survive.
    existing = device.attribute_bags.get("nautobot") or {}
    return device.model_copy(
        update={
            "status": DeviceStatus.OK,
            "capabilities": device.capabilities | {Capability.ATTRIBUTES},
            "attribute_bags": {
                **device.attribute_bags,
                "nautobot": {**existing, **bag_updates},
            },
        }
    )


async def _process_device(
    *,
    device_key: str,
    device: DeviceContext,
    node_id: str,
    parsed: _ParsedConfig,
    service: MetadataCreationService,
    shared: _SharedCalls,
) -> tuple[str, DeviceContext, bool]:
    try:
        values: dict[str, Any] = _resolve_fields(device, parsed)
        if parsed.metadata_type == _DEVICE_TYPE:
            values["height"] = _parse_height(values["height"])
        ensure = _ENSURERS[parsed.metadata_type]
        key = _identity_key(parsed.metadata_type, values)
        bag_updates = await shared.run(key, lambda: ensure(service, values))
    except _DeviceFailure as failure:
        return device_key, _fail(device, node_id, failure.code, failure.message), False
    except MetadataReferenceNotFoundError as exc:
        return device_key, _fail(device, node_id, "reference_not_found", str(exc)), False
    except Exception as exc:
        return device_key, _fail(device, node_id, type(exc).__name__.lower(), str(exc)), False
    return device_key, _enrich(device, bag_updates), True


def _build_outcomes(
    context: WorkflowContext, results: list[tuple[str, DeviceContext, bool]]
) -> list[StepOutcome]:
    success = {key: device for key, device, ok in results if ok}
    failed = {key: device for key, device, ok in results if not ok}
    outcomes = [
        StepOutcome(name="success", context=context.model_copy(update={"devices": success}))
    ]
    if failed:
        outcomes.append(
            StepOutcome(name="failure", context=context.model_copy(update={"devices": failed}))
        )
    return outcomes


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

    parsed = _parse_config(config)
    if not context.devices:
        raise ValueError(
            f"{_STEP_ID}: no devices in workflow context; "
            "connect an inventory step upstream (e.g. get-from-list)"
        )

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    credentials = resolve_nautobot_credentials(db, parsed.source_id, step_id=_STEP_ID)
    client = CredentialsBoundNautobotClient(service_factory.get_nautobot_app_service(), credentials)
    service = MetadataCreationService(client)
    shared = _SharedCalls()

    logger.info(
        "%s started run_id=%s source_id=%s metadata_type=%s devices=%d",
        _STEP_ID,
        run.id,
        parsed.source_id,
        parsed.metadata_type,
        len(context.devices),
    )

    results = await asyncio.gather(
        *[
            _process_device(
                device_key=device_key,
                device=device,
                node_id=node_id,
                parsed=parsed,
                service=service,
                shared=shared,
            )
            for device_key, device in context.devices.items()
        ]
    )

    success_count = sum(1 for _, _, ok in results if ok)
    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        _STEP_ID,
        success_count,
        len(results) - success_count,
        run.id,
    )
    return _build_outcomes(context, results)

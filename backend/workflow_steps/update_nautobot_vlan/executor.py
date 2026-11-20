"""Executor for the update-nautobot-vlan step.

All Nautobot work is done by the shared ``DeviceCommonService`` (VLANManager): the step resolves
the VLAN (by UUID, or by VID and optional VLAN group) and the new values per device, looks up
status, role, VLAN group and locations once per distinct value, and reports per device. An empty
field is left unchanged; the locations are replaced, extended or reduced depending on the mode.
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
from models.failure import FailureInfo, failure_from_exception
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.nautobot.common.exceptions import NautobotAmbiguousMatchError, NautobotNotFoundError
from services.nautobot.common.validators import is_valid_uuid
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.devices.common import DeviceCommonService
from services.nautobot.managers.vlan_manager import (
    LOCATIONS_MODES,
    LocationsMode,
    VlanPartialUpdateError,
)
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER
from workflow_steps.common.location_list import split_locations
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.partial_outcomes import (
    device_error_from_exception,
    fail_device_with_error,
)
from workflow_steps.common.step_flags import parse_bool_flag
from workflow_steps.common.update_field_expression import resolve_update_field_expression
from workflow_steps.update_nautobot_vlan.interfaces_mode import run_from_interfaces

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "update-nautobot-vlan"
_OUTCOME_NAMES = ("success", "failure")
_VLAN_CONTENT_TYPE = "ipam.vlan"
_CONCURRENCY = 5
# Fields whose name is looked up to the id Nautobot expects (name and description go as text).
_LOOKUP_FIELDS = ("status", "role")
_FIELDS = ("name", "description", "status", "role", "locations")
_VID_RANGE = range(1, 4095)


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    vlan_id_expression: str
    vid_expression: str
    vlan_group_expression: str
    expressions: dict[str, str]
    location_expressions: tuple[str, ...]
    locations_mode: LocationsMode
    from_interfaces: bool = False
    dry_run: bool = False


# Keys the "VLANs from interfaces" mode does not take: it only adds the device's own location.
_INTERFACE_MODE_REFUSED = ("vlan_id", "vid", "vlan_group", *_FIELDS)


@dataclass(frozen=True)
class _Bound:
    common: DeviceCommonService


def _text(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if isinstance(value, list):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    source_id = _text(config, "nautobot_source_id")
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is not configured")
    dry_run = parse_bool_flag(config, "dry_run")
    if parse_bool_flag(config, "vlans_from_interfaces"):
        extra = [key for key in _INTERFACE_MODE_REFUSED if _text(config, key)]
        if extra:
            raise ValueError(
                f"{_STEP_ID}: vlans_from_interfaces only adds the device's location; "
                f"clear {', '.join(extra)}"
            )
        return _ParsedConfig(
            source_id=source_id,
            vlan_id_expression="",
            vid_expression="",
            vlan_group_expression="",
            expressions={},
            location_expressions=(),
            locations_mode="add",
            from_interfaces=True,
            dry_run=dry_run,
        )
    if dry_run:
        # Only the interfaces mode previews; ignoring the flag here would write to Nautobot.
        raise ValueError(
            f"{_STEP_ID}: dry_run only works with vlans_from_interfaces; "
            "switch it off or the step would write"
        )
    vlan_id = _text(config, "vlan_id")
    vid = _text(config, "vid")
    if not vlan_id and not vid:
        raise ValueError(f"{_STEP_ID}: configure vlan_id or vid to select the VLAN")
    expressions = {field: _text(config, field) for field in _FIELDS if field != "locations"}
    locations = tuple(split_locations(_text(config, "locations")))
    if not any(expressions.values()) and not locations:
        raise ValueError(
            f"{_STEP_ID}: configure at least one field to update ({', '.join(_FIELDS)})"
        )
    mode = _text(config, "locations_mode") or "replace"
    if mode not in LOCATIONS_MODES:
        raise ValueError(f"{_STEP_ID}: locations_mode must be one of {', '.join(LOCATIONS_MODES)}")
    return _ParsedConfig(
        source_id=source_id,
        vlan_id_expression=vlan_id,
        vid_expression=vid,
        vlan_group_expression=_text(config, "vlan_group"),
        expressions=expressions,
        location_expressions=locations,
        locations_mode=mode,  # type: ignore[arg-type]  # checked against LOCATIONS_MODES above
    )


def _bind_nautobot(run: WorkflowRun, source_id: str) -> _Bound:
    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")
    credentials = resolve_nautobot_credentials(db, source_id, step_id=_STEP_ID)
    client = CredentialsBoundNautobotClient(service_factory.get_nautobot_app_service(), credentials)
    return _Bound(DeviceCommonService(client))


def _not_found_failure() -> FailureInfo:
    return FailureInfo(phase="api", kind="not_found", hint="check_request")


def _bad_request_failure() -> FailureInfo:
    return FailureInfo(phase="config", kind="bad_request", hint="check_request")


def _ambiguous_failure() -> FailureInfo:
    return FailureInfo(phase="api", kind="ambiguous_match", hint="check_request")


def _failed(
    device: DeviceContext, *, node_id: str, code: str, message: str, failure: FailureInfo
) -> DeviceContext:
    error = DeviceError(
        node_id=node_id, step_id=_STEP_ID, code=code, message=message, failure=failure
    )
    return fail_device_with_error(device, error)


@dataclass(frozen=True)
class _Plan:
    """One device's resolved values (names until ``_resolve_ids`` turns them into ids)."""

    device: DeviceContext
    vlan_id: str | None
    vid: int | None
    vlan_group: str | None
    values: dict[str, str]
    locations: tuple[str, ...]


def _plan_device(
    parsed: _ParsedConfig, device: DeviceContext, run_id: str
) -> _Plan | tuple[str, str, FailureInfo]:
    """A ``_Plan``, or ``(code, message, failure)`` when the device cannot be updated."""

    def resolve(field: str, raw: str) -> str | tuple[str, str, FailureInfo]:
        # reveal_secrets=False: the values are copied into a Nautobot request and error text.
        value = resolve_update_field_expression(
            device=device, field_key=field, raw_value=raw, run_id=run_id, reveal_secrets=False
        )
        if value == REDACTED_PLACEHOLDER:
            return (
                f"{field}_is_secret",
                f"{field} expression {raw!r} points to a secret, which this step does not copy",
                _bad_request_failure(),
            )
        if value is None:
            return (
                f"{field}_unresolved",
                f"{field} expression {raw!r} resolved to nothing",
                _bad_request_failure(),
            )
        return value.strip()

    resolved: dict[str, str] = {}
    pairs = (
        ("vlan_id", parsed.vlan_id_expression),
        ("vid", parsed.vid_expression),
        ("vlan_group", parsed.vlan_group_expression),
        *parsed.expressions.items(),
    )
    for field, raw in pairs:
        if not raw:
            continue
        value = resolve(field, raw)
        if isinstance(value, tuple):
            return value
        resolved[field] = value

    locations: list[str] = []
    for raw in parsed.location_expressions:
        value = resolve("locations", raw)
        if isinstance(value, tuple):
            return value
        # Only an expression can resolve to a list; a fixed entry is already one location.
        is_expression = raw.startswith("{")
        locations.extend(split_locations(value) if is_expression else [value] if value else [])

    vlan_id = resolved.pop("vlan_id", "")
    vid_text = resolved.pop("vid", "")
    group = resolved.pop("vlan_group", "")
    vid: int | None = None
    if vlan_id:
        # The value is not echoed: it can come from an attribute and ends up in the stored error.
        if not is_valid_uuid(vlan_id.lower()):
            return "vlan_id_invalid", "vlan_id is not a Nautobot UUID", _bad_request_failure()
    else:
        if not vid_text.isdigit() or int(vid_text) not in _VID_RANGE:
            return "vid_invalid", "vid must be a number from 1 to 4094", _bad_request_failure()
        vid = int(vid_text)

    values = {field: value for field, value in resolved.items() if value}
    if not values and not locations:
        return "nothing_to_update", "Every field resolved to an empty value", _bad_request_failure()
    return _Plan(
        device=device,
        vlan_id=vlan_id.lower() or None,
        vid=vid,
        vlan_group=group or None,
        values=values,
        locations=tuple(dict.fromkeys(locations)),
    )


# The looked-up name is never repeated: it can come from a device attribute.
_LOOKUP_MESSAGES = {
    "status_not_found": "The status was not found for VLANs in Nautobot",
    "role_not_found": "The role was not found for VLANs in Nautobot",
    "vlan_group_not_found": "The VLAN group was not found in Nautobot",
    "location_not_found": "A location was not found in Nautobot",
    "ambiguous_match": "More than one Nautobot object matches a name; use its UUID instead",
}


async def _role_id(common: DeviceCommonService, name: str) -> str:
    role_id = await common.resolve_role_id_for_content_type(name, _VLAN_CONTENT_TYPE)
    if role_id is None:
        raise ValueError(_LOOKUP_MESSAGES["role_not_found"])
    return role_id


async def _status_id(common: DeviceCommonService, name: str) -> str:
    return await common.resolve_status_id(name, content_type=_VLAN_CONTENT_TYPE)


# kind -> (error code when a ValueError says "not found", resolver name -> id)
_LOOKUPS: dict[str, tuple[str, Callable[[DeviceCommonService, str], Awaitable[str]]]] = {
    "status": ("status_not_found", _status_id),
    "role": ("role_not_found", _role_id),
    "vlan_group": (
        "vlan_group_not_found",
        lambda common, name: common.resolve_vlan_group_id(name),
    ),
    "location": (
        "location_not_found",
        lambda common, name: common.resolve_location_id_strict(name),
    ),
}


@dataclass(frozen=True)
class _Resolved:
    plan: _Plan
    fields: dict[str, str]
    location_ids: tuple[str, ...]
    group_id: str | None


class _Lookups:
    """Name -> id lookups, each distinct value asked of Nautobot once per execution."""

    def __init__(self, common: DeviceCommonService) -> None:
        self._common = common
        self._cache: dict[tuple[str, str], str | Exception] = {}

    async def get(self, kind: str, name: str) -> str | tuple[str, Exception]:
        key = (kind, name)
        if key not in self._cache:
            _, resolver = _LOOKUPS[kind]
            try:
                self._cache[key] = await resolver(self._common, name)
            except Exception as exc:
                self._cache[key] = exc
        found = self._cache[key]
        if isinstance(found, Exception):
            return _LOOKUPS[kind][0], found
        return found


async def _resolve_ids(lookups: _Lookups, plan: _Plan) -> _Resolved | tuple[str, Exception]:
    fields = dict(plan.values)
    for kind in _LOOKUP_FIELDS:
        if kind not in fields:
            continue
        found = await lookups.get(kind, fields[kind])
        if isinstance(found, tuple):
            return found
        fields[kind] = found
    group_id: str | None = None
    if plan.vlan_group:
        found = await lookups.get("vlan_group", plan.vlan_group)
        if isinstance(found, tuple):
            return found
        group_id = found
    location_ids: list[str] = []
    for name in plan.locations:
        found = await lookups.get("location", name)
        if isinstance(found, tuple):
            return found
        location_ids.append(found)
    return _Resolved(plan, fields, tuple(dict.fromkeys(location_ids)), group_id)


def _lookup_error(code: str, exc: Exception, node_id: str, device: DeviceContext) -> DeviceContext:
    if isinstance(exc, NautobotAmbiguousMatchError):
        return _failed(
            device,
            node_id=node_id,
            code="ambiguous_match",
            message=_LOOKUP_MESSAGES["ambiguous_match"],
            failure=_ambiguous_failure(),
        )
    if isinstance(exc, ValueError):
        return _failed(
            device,
            node_id=node_id,
            code=code,
            message=_LOOKUP_MESSAGES[code],
            failure=_not_found_failure(),
        )
    return fail_device_with_error(
        device, device_error_from_exception(exc, node_id=node_id, step_id=_STEP_ID)
    )


async def _select_vlan(
    common: DeviceCommonService, resolved: _Resolved, found: dict[tuple[int, str | None], list[str]]
) -> str | tuple[str, str, FailureInfo]:
    """The VLAN id, or ``(code, message, failure)`` for none / several matches."""
    plan = resolved.plan
    if plan.vlan_id:
        return plan.vlan_id
    if plan.vid is None:  # _plan_device guarantees a vlan_id or a vid
        return "vid_invalid", "vid must be a number from 1 to 4094", _bad_request_failure()
    key = (plan.vid, resolved.group_id)
    if key not in found:
        found[key] = await common.find_vlans(plan.vid, resolved.group_id)
    ids = found[key]
    if not ids:
        return "vlan_not_found", "No VLAN with this VID was found in Nautobot", _not_found_failure()
    if len(ids) > 1:
        return (
            "ambiguous_match",
            "More than one VLAN has this VID; set vlan_group or use vlan_id",
            _ambiguous_failure(),
        )
    return ids[0]


async def _update(
    bound: _Bound,
    resolved: _Resolved,
    mode: LocationsMode,
    found: dict[tuple[int, str | None], list[str]],
    node_id: str,
) -> tuple[str, DeviceContext, bool]:
    device = resolved.plan.device
    try:
        selected = await _select_vlan(bound.common, resolved, found)
        if isinstance(selected, tuple):
            code, message, failure = selected
            return (
                "failure",
                _failed(device, node_id=node_id, code=code, message=message, failure=failure),
                False,
            )
        changed = await bound.common.update_vlan(
            selected,
            resolved.fields,
            locations=resolved.location_ids,
            locations_mode=mode,
        )
    except VlanPartialUpdateError as exc:
        # Part of the change is stored: say so; running the step again completes it.
        applied = " and ".join(exc.applied)
        return (
            "failure",
            _failed(
                device,
                node_id=node_id,
                code="vlan_partially_updated",
                message=(
                    f"The VLAN was changed only in part: {applied} already written in Nautobot; "
                    "run the step again to complete it"
                ),
                failure=failure_from_exception(exc)
                or FailureInfo(phase="api", kind="unknown", retryable=True),
            ),
            False,
        )
    except NautobotNotFoundError:
        return (
            "failure",
            _failed(
                device,
                node_id=node_id,
                code="vlan_not_found",
                message="The VLAN was not found in Nautobot",
                failure=_not_found_failure(),
            ),
            False,
        )
    except Exception as exc:
        error = device_error_from_exception(exc, node_id=node_id, step_id=_STEP_ID)
        return "failure", fail_device_with_error(device, error), False
    return "success", device, changed


def _build_outcomes(
    *,
    context: WorkflowContext,
    node_id: str,
    buckets: dict[str, dict[str, DeviceContext]],
    updated: int,
) -> list[StepOutcome]:
    counts = {
        "updated": updated,
        "unchanged": len(buckets["success"]) - updated,
        "failed": len(buckets["failure"]),
    }
    metadata = {**context.metadata, f"{node_id}.update_vlan_counts": counts}
    return [
        StepOutcome(
            name=name,
            context=context.model_copy(
                update={"devices": dict(buckets[name]), "metadata": metadata}
            ),
        )
        for name in _OUTCOME_NAMES
    ]


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
    buckets: dict[str, dict[str, DeviceContext]] = {name: {} for name in _OUTCOME_NAMES}
    if not context.devices:
        return _build_outcomes(context=context, node_id=node_id, buckets=buckets, updated=0)

    bound = _bind_nautobot(run, parsed.source_id)
    if parsed.from_interfaces:
        return await run_from_interfaces(
            common=bound.common, context=context, node_id=node_id, dry_run=parsed.dry_run
        )
    logger.info(
        "update-nautobot-vlan started run_id=%s node_id=%s devices=%d",
        context.run_id,
        node_id,
        len(context.devices),
    )

    results: dict[str, tuple[str, DeviceContext]] = {}
    ready: list[_Resolved] = []
    lookups = _Lookups(bound.common)
    for device in context.devices.values():
        planned = _plan_device(parsed, device, context.run_id)
        if isinstance(planned, tuple):
            code, message, failure = planned
            results[device.id] = (
                "failure",
                _failed(device, node_id=node_id, code=code, message=message, failure=failure),
            )
            continue
        # Resolved one device after another so a shared name is looked up exactly once.
        resolved = await _resolve_ids(lookups, planned)
        if isinstance(resolved, tuple):
            code, exc = resolved
            results[device.id] = ("failure", _lookup_error(code, exc, node_id, device))
        else:
            ready.append(resolved)

    gate = asyncio.Semaphore(_CONCURRENCY)
    found: dict[tuple[int, str | None], list[str]] = {}

    async def run_one(item: _Resolved) -> tuple[str, DeviceContext, bool]:
        async with gate:
            return await _update(bound, item, parsed.locations_mode, found, node_id)

    done = await asyncio.gather(*[run_one(item) for item in ready])
    updated = 0
    for item, (bucket, device, changed) in zip(ready, done, strict=True):
        results[item.plan.device.id] = (bucket, device)
        updated += int(changed)

    for device_id in context.devices:
        bucket, device = results[device_id]
        buckets[bucket][device_id] = device

    logger.info(
        "update-nautobot-vlan finished success=%d failure=%d updated=%d run_id=%s",
        len(buckets["success"]),
        len(buckets["failure"]),
        updated,
        context.run_id,
    )
    return _build_outcomes(context=context, node_id=node_id, buckets=buckets, updated=updated)

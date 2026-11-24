"""One pipeline for the manual mode of Update VLAN and Update IP Prefix (W5-03).

``update-nautobot-vlan`` (Update VLAN) and ``update-nautobot-prefix`` (Update IP Prefix) change one
existing Nautobot object per device: *parse -> per-device plan (expressions, secret refusal) ->
name lookups with a shared cache -> select the object -> one write per distinct change -> outcomes
with ``updated`` / ``unchanged`` / ``failed`` counts*. They differ only in what the object is
called, how it is selected (a UUID, or a key plus an optional scope) and which manager call writes
it; that is an ``ObjectUpdateSpec``. A step keeps its own ``config.py``, ``_parse_config`` and
``interfaces_mode.py``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from models.failure import FailureInfo, failure_from_exception
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.nautobot.common.exceptions import NautobotAmbiguousMatchError, NautobotNotFoundError
from services.nautobot.common.validators import is_valid_uuid
from services.nautobot.devices.common import DeviceCommonService
from services.nautobot.managers.location_assignments import LocationsMode
from workflow_steps.common.location_list import split_locations
from workflow_steps.common.nautobot_plan_fields import (
    OUTCOME_NAMES,
    NameLookups,
    PlanError,
    ambiguous_failure,
    bad_request_failure,
    build_update_outcomes,
    failed,
    not_found_failure,
    resolve_field,
)
from workflow_steps.common.nautobot_write_groups import write_once_per_group
from workflow_steps.common.partial_outcomes import (
    NAUTOBOT_TEXT,
    device_error_from_exception,
    fail_device_with_error,
)

logger = logging.getLogger(__name__)

_CONCURRENCY = 5


@dataclass(frozen=True)
class ObjectUpdateSpec:
    """What one step contributes to the pipeline.

    ``key_field`` / ``scope_field`` are the config keys of the second way to select an object
    (``vid`` + ``vlan_group``, ``prefix`` + ``namespace``); ``normalize_key`` returns the key in the
    form the lookup is cached by, or ``None`` when it is not valid.
    """

    step_id: str
    noun: str  # "VLAN", "prefix": used in messages and in the codes ("vlan_not_found")
    plural: str
    code_stem: str  # "vlan", "prefix"
    content_type: str
    counts_key: str
    id_field: str  # "vlan_id", "prefix_id"
    key_field: str
    scope_field: str
    scope_label: str  # "VLAN group", "namespace": for the "not found" message
    scope_ignored_with_id: bool  # a UUID makes the scope irrelevant (it is not even looked up)
    normalize_key: Callable[[str], str | None]
    key_invalid_message: str
    no_match_message: str
    several_match_message: str
    resolve_scope: Callable[[DeviceCommonService, str], Awaitable[str]]
    find: Callable[[DeviceCommonService, str, str | None], Awaitable[list[str]]]
    update: Callable[..., Awaitable[bool]]
    partial_error: type[Exception]


@dataclass(frozen=True)
class ObjectUpdateRequest:
    """The parsed config of one step, in the shape the pipeline reads."""

    id_expression: str
    key_expression: str
    scope_expression: str
    expressions: dict[str, str]
    location_expressions: tuple[str, ...]
    locations_mode: LocationsMode


@dataclass(frozen=True)
class _Plan:
    """One device's resolved values (names until the lookups turn them into ids)."""

    device: DeviceContext
    object_id: str | None
    key: str | None
    scope: str | None
    values: dict[str, str]
    locations: tuple[str, ...]


@dataclass(frozen=True)
class _Resolved:
    plan: _Plan
    fields: dict[str, str]
    location_ids: tuple[str, ...]
    scope_id: str | None

    @property
    def target(self) -> tuple[str | None, str | None, str | None]:
        return self.plan.object_id, self.plan.key, self.scope_id


def plan_device(
    spec: ObjectUpdateSpec, request: ObjectUpdateRequest, device: DeviceContext, run_id: str
) -> _Plan | PlanError:
    """A plan, or ``(code, message, failure)`` when the device cannot be updated."""
    resolved: dict[str, str] = {}
    pairs = (
        (spec.id_field, request.id_expression),
        (spec.key_field, request.key_expression),
        (spec.scope_field, request.scope_expression),
        *request.expressions.items(),
    )
    for field, raw in pairs:
        if not raw:
            continue
        value = resolve_field(device, run_id, field, raw)
        if isinstance(value, tuple):
            return value
        resolved[field] = value

    locations: list[str] = []
    for raw in request.location_expressions:
        value = resolve_field(device, run_id, "locations", raw)
        if isinstance(value, tuple):
            return value
        # Only an expression can resolve to a list; a fixed entry is already one location.
        is_expression = raw.startswith("{")
        locations.extend(split_locations(value) if is_expression else [value] if value else [])

    object_id = resolved.pop(spec.id_field, "")
    key_text = resolved.pop(spec.key_field, "")
    scope = resolved.pop(spec.scope_field, "")
    key: str | None = None
    if object_id:
        # The value is not echoed: it can come from an attribute and ends up in the stored error.
        if not is_valid_uuid(object_id.lower()):
            return (
                f"{spec.id_field}_invalid",
                f"{spec.id_field} is not a Nautobot UUID",
                bad_request_failure(),
            )
    else:
        key = spec.normalize_key(key_text)
        if key is None:
            return f"{spec.key_field}_invalid", spec.key_invalid_message, bad_request_failure()

    values = {field: value for field, value in resolved.items() if value}
    if not values and not locations:
        return "nothing_to_update", "Every field resolved to an empty value", bad_request_failure()
    return _Plan(
        device=device,
        object_id=object_id.lower() or None,
        key=key,
        scope=scope or None,
        values=values,
        locations=tuple(dict.fromkeys(locations)),
    )


def _lookup_table(spec: ObjectUpdateSpec) -> dict[str, tuple[str, Any]]:
    async def role(common: DeviceCommonService, name: str) -> str:
        role_id = await common.resolve_role_id_for_content_type(name, spec.content_type)
        if role_id is None:
            raise ValueError(_lookup_messages(spec)["role_not_found"])
        return role_id

    async def status(common: DeviceCommonService, name: str) -> str:
        return await common.resolve_status_id(name, content_type=spec.content_type)

    return {
        "status": ("status_not_found", status),
        "role": ("role_not_found", role),
        "scope": (
            f"{spec.scope_field}_not_found",
            lambda common, name: spec.resolve_scope(common, name),
        ),
        "location": (
            "location_not_found",
            lambda common, name: common.resolve_location_id_strict(name),
        ),
    }


def _lookup_messages(spec: ObjectUpdateSpec) -> dict[str, str]:
    # The looked-up name is never repeated: it can come from a device attribute.
    return {
        "status_not_found": f"The status was not found for {spec.plural} in Nautobot",
        "role_not_found": f"The role was not found for {spec.plural} in Nautobot",
        f"{spec.scope_field}_not_found": f"The {spec.scope_label} was not found in Nautobot",
        "location_not_found": "A location was not found in Nautobot",
        "ambiguous_match": "More than one Nautobot object matches a name; use its UUID instead",
    }


async def _resolve_ids(
    spec: ObjectUpdateSpec, lookups: NameLookups, plan: _Plan
) -> _Resolved | tuple[str, Exception]:
    fields = dict(plan.values)
    for kind in ("status", "role"):
        if kind not in fields:
            continue
        found = await lookups.get(kind, fields[kind])
        if isinstance(found, tuple):
            return found
        fields[kind] = found
    scope_id: str | None = None
    if plan.scope and not (spec.scope_ignored_with_id and plan.object_id):
        found = await lookups.get("scope", plan.scope)
        if isinstance(found, tuple):
            return found
        scope_id = found
    location_ids: list[str] = []
    for name in plan.locations:
        found = await lookups.get("location", name)
        if isinstance(found, tuple):
            return found
        location_ids.append(found)
    return _Resolved(plan, fields, tuple(dict.fromkeys(location_ids)), scope_id)


def _lookup_error(
    spec: ObjectUpdateSpec, code: str, exc: Exception, node_id: str, device: DeviceContext
) -> DeviceContext:
    messages = _lookup_messages(spec)
    if isinstance(exc, NautobotAmbiguousMatchError):
        return failed(
            spec.step_id,
            device,
            node_id=node_id,
            code="ambiguous_match",
            message=messages["ambiguous_match"],
            failure=ambiguous_failure(),
        )
    if isinstance(exc, ValueError):
        return failed(
            spec.step_id,
            device,
            node_id=node_id,
            code=code,
            message=messages[code],
            failure=not_found_failure(),
        )
    return fail_device_with_error(
        device, device_error_from_exception(
            exc, node_id=node_id, step_id=spec.step_id, keep_text=NAUTOBOT_TEXT
        )
    )


_Found = dict[tuple[str, str | None], list[str]]


async def _select_object(
    spec: ObjectUpdateSpec, common: DeviceCommonService, resolved: _Resolved, found: _Found
) -> str | PlanError:
    """The object id, or ``(code, message, failure)`` for none / several matches."""
    plan = resolved.plan
    if plan.object_id:
        return plan.object_id
    if plan.key is None:  # plan_device guarantees an id or a key
        return f"{spec.key_field}_invalid", spec.key_invalid_message, bad_request_failure()
    cache_key = (plan.key, resolved.scope_id)
    if cache_key not in found:
        found[cache_key] = await spec.find(common, plan.key, resolved.scope_id)
    ids = found[cache_key]
    if not ids:
        return f"{spec.code_stem}_not_found", spec.no_match_message, not_found_failure()
    if len(ids) > 1:
        return "ambiguous_match", spec.several_match_message, ambiguous_failure()
    return ids[0]


# (outcome handle, device, whether the write changed the object)
_Written = tuple[str, DeviceContext, bool]


async def _update(
    spec: ObjectUpdateSpec,
    common: DeviceCommonService,
    resolved: _Resolved,
    mode: LocationsMode,
    found: _Found,
    node_id: str,
) -> _Written:
    device = resolved.plan.device

    def fail(code: str, message: str, failure: FailureInfo) -> _Written:
        return (
            "failure",
            failed(
                spec.step_id,
                device,
                node_id=node_id,
                code=code,
                message=message,
                failure=failure,
            ),
            False,
        )

    try:
        selected = await _select_object(spec, common, resolved, found)
        if isinstance(selected, tuple):
            return fail(*selected)
        changed = await spec.update(
            common,
            selected,
            resolved.fields,
            locations=resolved.location_ids,
            locations_mode=mode,
        )
    except spec.partial_error as exc:
        # Part of the change is stored: say so; running the step again completes it.
        applied = " and ".join(getattr(exc, "applied", ()))
        return fail(
            f"{spec.code_stem}_partially_updated",
            (
                f"The {spec.noun} was changed only in part: {applied} already written in "
                "Nautobot; run the step again to complete it"
            ),
            failure_from_exception(exc) or FailureInfo(phase="api", kind="unknown", retryable=True),
        )
    except NautobotNotFoundError:
        return (
            "failure",
            failed(
                spec.step_id,
                device,
                node_id=node_id,
                code=f"{spec.code_stem}_not_found",
                message=f"The {spec.noun} was not found in Nautobot",
                failure=not_found_failure(),
            ),
            False,
        )
    except Exception as exc:
        error = device_error_from_exception(
            exc, node_id=node_id, step_id=spec.step_id, keep_text=NAUTOBOT_TEXT
        )
        return "failure", fail_device_with_error(device, error), False
    return "success", device, changed


def empty_outcomes(
    spec: ObjectUpdateSpec, context: WorkflowContext, node_id: str
) -> list[StepOutcome]:
    """Both outcomes with zero counts (no devices)."""
    buckets: dict[str, dict[str, DeviceContext]] = {name: {} for name in OUTCOME_NAMES}
    return build_update_outcomes(
        context=context,
        node_id=node_id,
        buckets=buckets,
        updated=0,
        counts_key=spec.counts_key,
    )


async def run_object_update(
    spec: ObjectUpdateSpec,
    request: ObjectUpdateRequest,
    *,
    common: DeviceCommonService,
    context: WorkflowContext,
    node_id: str,
) -> list[StepOutcome]:
    """Update the selected object for every device and return the two outcomes."""
    logger.info(
        "%s started run_id=%s node_id=%s devices=%d",
        spec.step_id,
        context.run_id,
        node_id,
        len(context.devices),
    )
    results: dict[str, tuple[str, DeviceContext]] = {}
    ready: list[_Resolved] = []
    lookups = NameLookups(common, _lookup_table(spec))
    for device in context.devices.values():
        planned = plan_device(spec, request, device, context.run_id)
        if isinstance(planned, tuple):
            code, message, failure = planned
            results[device.id] = (
                "failure",
                failed(
                    spec.step_id,
                    device,
                    node_id=node_id,
                    code=code,
                    message=message,
                    failure=failure,
                ),
            )
            continue
        # Resolved one device after another so a shared name is looked up exactly once.
        resolved = await _resolve_ids(spec, lookups, planned)
        if isinstance(resolved, tuple):
            code, exc = resolved
            results[device.id] = ("failure", _lookup_error(spec, code, exc, node_id, device))
        else:
            ready.append(resolved)

    gate = asyncio.Semaphore(_CONCURRENCY)
    found: _Found = {}

    async def write(item: _Resolved) -> _Written:
        return await _update(spec, common, item, request.locations_mode, found, node_id)

    # Devices that resolve to one object with the same values share one write (W5-01, D6).
    done = await write_once_per_group(
        ready,
        target_of=lambda item: item.target,
        group_of=lambda item: (
            item.target,
            tuple(sorted(item.fields.items())),
            item.location_ids,
        ),
        device_of=lambda item: item.plan.device,
        write=write,
        gate=gate,
    )
    updated = 0
    for item, (bucket, device, changed) in zip(ready, done, strict=True):
        results[item.plan.device.id] = (bucket, device)
        updated += int(changed)

    buckets: dict[str, dict[str, DeviceContext]] = {name: {} for name in OUTCOME_NAMES}
    for device_id in context.devices:
        bucket, device = results[device_id]
        buckets[bucket][device_id] = device

    logger.info(
        "%s finished success=%d failure=%d updated=%d run_id=%s",
        spec.step_id,
        len(buckets["success"]),
        len(buckets["failure"]),
        updated,
        context.run_id,
    )
    return build_update_outcomes(
        context=context,
        node_id=node_id,
        buckets=buckets,
        updated=updated,
        counts_key=spec.counts_key,
    )

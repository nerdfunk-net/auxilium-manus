"""Executor for the update-nautobot-prefix step.

Changes an existing IP prefix in Nautobot through the shared ``DeviceCommonService``
(``PrefixManager.update_prefix``): the prefix is selected by UUID or by network and namespace, the
new values are resolved per device, status, role, namespace and location names are looked up once
per distinct value, and every device is reported. An empty field is left unchanged; the locations
are replaced, extended or reduced depending on the mode. ``prefixes_from_interfaces`` instead adds
each device's own location to the parent prefixes of its interface addresses
(``interfaces_mode.py``).
"""

from __future__ import annotations

import asyncio
import ipaddress
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
from services.nautobot.managers.location_assignments import (
    LOCATIONS_MODES,
    LocationsMode,
    PartialUpdateError,
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
from workflow_steps.update_nautobot_prefix.interfaces_mode import run_from_interfaces

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "update-nautobot-prefix"
_OUTCOME_NAMES = ("success", "failure")
_CONTENT_TYPE = "ipam.prefix"
_CONCURRENCY = 5
_FIELDS = ("description", "status", "role", "locations")
_VALUE_FIELDS = ("description", "status", "role")
# Keys the "prefixes from interfaces" mode does not take: it only adds the device's own location.
_INTERFACE_MODE_REFUSED = ("prefix_id", "prefix", "namespace", *_FIELDS)

_LOOKUP_MESSAGES = {
    "status_not_found": "The status was not found for prefixes in Nautobot",
    "role_not_found": "The role was not found for prefixes in Nautobot",
    "namespace_not_found": "The namespace was not found in Nautobot",
    "location_not_found": "A location was not found in Nautobot",
    "ambiguous_match": "More than one Nautobot object matches a name; use its UUID instead",
}


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    prefix_id_expression: str
    prefix_expression: str
    namespace_expression: str
    expressions: dict[str, str]
    location_expressions: tuple[str, ...]
    locations_mode: LocationsMode
    from_interfaces: bool = False
    dry_run: bool = False


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
    if parse_bool_flag(config, "prefixes_from_interfaces"):
        extra = [key for key in _INTERFACE_MODE_REFUSED if _text(config, key)]
        if extra:
            raise ValueError(
                f"{_STEP_ID}: prefixes_from_interfaces only adds the device's location; "
                f"clear {', '.join(extra)}"
            )
        return _ParsedConfig(
            source_id=source_id,
            prefix_id_expression="",
            prefix_expression="",
            namespace_expression="",
            expressions={},
            location_expressions=(),
            locations_mode="add",
            from_interfaces=True,
            dry_run=dry_run,
        )
    if dry_run:
        # Only the interfaces mode previews; ignoring the flag here would write to Nautobot.
        raise ValueError(
            f"{_STEP_ID}: dry_run only works with prefixes_from_interfaces; "
            "switch it off or the step would write"
        )
    prefix_id = _text(config, "prefix_id")
    prefix = _text(config, "prefix")
    if not prefix_id and not prefix:
        raise ValueError(f"{_STEP_ID}: configure prefix_id or prefix to select the prefix")
    expressions = {field: _text(config, field) for field in _VALUE_FIELDS}
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
        prefix_id_expression=prefix_id,
        prefix_expression=prefix,
        namespace_expression=_text(config, "namespace"),
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


def _failure(phase: str, kind: str) -> FailureInfo:
    return FailureInfo(phase=phase, kind=kind, hint="check_request")  # type: ignore[arg-type]


def _failed(device: DeviceContext, *, node_id: str, code: str, message: str, failure: FailureInfo):
    error = DeviceError(
        node_id=node_id, step_id=_STEP_ID, code=code, message=message, failure=failure
    )
    return fail_device_with_error(device, error)


@dataclass(frozen=True)
class _Plan:
    device: DeviceContext
    prefix_id: str | None
    prefix: str | None
    namespace: str | None
    values: dict[str, str]
    locations: tuple[str, ...]


_PlanError = tuple[str, str, FailureInfo]


def _plan_device(parsed: _ParsedConfig, device: DeviceContext, run_id: str) -> _Plan | _PlanError:
    def resolve(field: str, raw: str) -> str | _PlanError:
        # reveal_secrets=False: the values are copied into a Nautobot request and error text.
        value = resolve_update_field_expression(
            device=device, field_key=field, raw_value=raw, run_id=run_id, reveal_secrets=False
        )
        if value == REDACTED_PLACEHOLDER:
            return (
                f"{field}_is_secret",
                f"{field} expression {raw!r} points to a secret, which this step does not copy",
                _failure("config", "bad_request"),
            )
        if value is None:
            return (
                f"{field}_unresolved",
                f"{field} expression {raw!r} resolved to nothing",
                _failure("config", "bad_request"),
            )
        return value.strip()

    resolved: dict[str, str] = {}
    pairs = (
        ("prefix_id", parsed.prefix_id_expression),
        ("prefix", parsed.prefix_expression),
        ("namespace", parsed.namespace_expression),
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

    prefix_id = resolved.pop("prefix_id", "")
    prefix = resolved.pop("prefix", "")
    namespace = resolved.pop("namespace", "")
    if prefix_id:
        # The value is not echoed: it can come from an attribute and ends up in the stored error.
        if not is_valid_uuid(prefix_id.lower()):
            return (
                "prefix_id_invalid",
                "prefix_id is not a Nautobot UUID",
                _failure("config", "bad_request"),
            )
    else:
        try:
            # The canonical text is what Nautobot stores and what the lookup cache is keyed by.
            prefix = str(ipaddress.ip_network(prefix, strict=True))
        except ValueError:
            return (
                "prefix_invalid",
                "prefix is not a network address like 10.0.0.0/24",
                _failure("config", "bad_request"),
            )
    values = {field: value for field, value in resolved.items() if value}
    if not values and not locations:
        return (
            "nothing_to_update",
            "Every field resolved to an empty value",
            _failure("config", "bad_request"),
        )
    return _Plan(
        device=device,
        prefix_id=prefix_id.lower() or None,
        prefix=prefix or None,
        namespace=namespace or None,
        values=values,
        locations=tuple(dict.fromkeys(locations)),
    )


async def _status_id(common: DeviceCommonService, name: str) -> str:
    return await common.resolve_status_id(name, content_type=_CONTENT_TYPE)


async def _role_id(common: DeviceCommonService, name: str) -> str:
    role_id = await common.resolve_role_id_for_content_type(name, _CONTENT_TYPE)
    if role_id is None:
        raise ValueError(_LOOKUP_MESSAGES["role_not_found"])
    return role_id


_LOOKUPS: dict[str, tuple[str, Callable[[DeviceCommonService, str], Awaitable[str]]]] = {
    "status": ("status_not_found", _status_id),
    "role": ("role_not_found", _role_id),
    "namespace": ("namespace_not_found", lambda common, name: common.resolve_namespace_id(name)),
    "location": (
        "location_not_found",
        lambda common, name: common.resolve_location_id_strict(name),
    ),
}


class _Lookups:
    """Name -> id lookups, each distinct value asked of Nautobot once per execution."""

    def __init__(self, common: DeviceCommonService) -> None:
        self._common = common
        self._cache: dict[tuple[str, str], str | Exception] = {}

    async def get(self, kind: str, name: str) -> str | tuple[str, Exception]:
        key = (kind, name)
        if key not in self._cache:
            try:
                self._cache[key] = await _LOOKUPS[kind][1](self._common, name)
            except Exception as exc:
                self._cache[key] = exc
        found = self._cache[key]
        if isinstance(found, Exception):
            return _LOOKUPS[kind][0], found
        return found


@dataclass(frozen=True)
class _Resolved:
    plan: _Plan
    fields: dict[str, str]
    location_ids: tuple[str, ...]
    namespace_id: str | None


async def _resolve_ids(lookups: _Lookups, plan: _Plan) -> _Resolved | tuple[str, Exception]:
    fields = dict(plan.values)
    for kind in ("status", "role"):
        if kind not in fields:
            continue
        found = await lookups.get(kind, fields[kind])
        if isinstance(found, tuple):
            return found
        fields[kind] = found
    namespace_id: str | None = None
    if plan.namespace and not plan.prefix_id:
        found = await lookups.get("namespace", plan.namespace)
        if isinstance(found, tuple):
            return found
        namespace_id = found
    location_ids: list[str] = []
    for name in plan.locations:
        found = await lookups.get("location", name)
        if isinstance(found, tuple):
            return found
        location_ids.append(found)
    return _Resolved(plan, fields, tuple(dict.fromkeys(location_ids)), namespace_id)


def _lookup_error(code: str, exc: Exception, node_id: str, device: DeviceContext) -> DeviceContext:
    if isinstance(exc, NautobotAmbiguousMatchError):
        return _failed(
            device,
            node_id=node_id,
            code="ambiguous_match",
            message=_LOOKUP_MESSAGES["ambiguous_match"],
            failure=_failure("api", "ambiguous_match"),
        )
    if isinstance(exc, ValueError):
        return _failed(
            device,
            node_id=node_id,
            code=code,
            message=_LOOKUP_MESSAGES[code],
            failure=_failure("api", "not_found"),
        )
    return fail_device_with_error(
        device, device_error_from_exception(exc, node_id=node_id, step_id=_STEP_ID)
    )


async def _select_prefix(
    common: DeviceCommonService,
    resolved: _Resolved,
    found: dict[tuple[str, str | None], list[str]],
) -> str | _PlanError:
    """The prefix id, or ``(code, message, failure)`` for none / several matches."""
    plan = resolved.plan
    if plan.prefix_id:
        return plan.prefix_id
    key = (plan.prefix or "", resolved.namespace_id)
    if key not in found:
        found[key] = await common.find_prefixes(*key)
    ids = found[key]
    if not ids:
        return (
            "prefix_not_found",
            "No prefix with this network was found in Nautobot",
            _failure("api", "not_found"),
        )
    if len(ids) > 1:
        return (
            "ambiguous_match",
            "The prefix exists in more than one namespace; set namespace or use prefix_id",
            _failure("api", "ambiguous_match"),
        )
    return ids[0]


async def _update(
    bound: _Bound,
    resolved: _Resolved,
    mode: LocationsMode,
    found: dict[tuple[str, str | None], list[str]],
    node_id: str,
) -> tuple[str, DeviceContext, bool]:
    device = resolved.plan.device
    try:
        selected = await _select_prefix(bound.common, resolved, found)
        if isinstance(selected, tuple):
            code, message, failure = selected
            return (
                "failure",
                _failed(device, node_id=node_id, code=code, message=message, failure=failure),
                False,
            )
        changed = await bound.common.update_prefix(
            selected, resolved.fields, locations=resolved.location_ids, locations_mode=mode
        )
    except PartialUpdateError as exc:
        # Part of the change is stored: say so; running the step again completes it.
        applied = " and ".join(exc.applied)
        return (
            "failure",
            _failed(
                device,
                node_id=node_id,
                code="prefix_partially_updated",
                message=(
                    f"The prefix was changed only in part: {applied} already written in "
                    "Nautobot; run the step again to complete it"
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
                code="prefix_not_found",
                message="The prefix was not found in Nautobot",
                failure=_failure("api", "not_found"),
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
    metadata = {**context.metadata, f"{node_id}.update_prefix_counts": counts}
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
        "update-nautobot-prefix started run_id=%s node_id=%s devices=%d",
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
    found: dict[tuple[str, str | None], list[str]] = {}

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
        "update-nautobot-prefix finished success=%d failure=%d updated=%d run_id=%s",
        len(buckets["success"]),
        len(buckets["failure"]),
        updated,
        context.run_id,
    )
    return _build_outcomes(context=context, node_id=node_id, buckets=buckets, updated=updated)

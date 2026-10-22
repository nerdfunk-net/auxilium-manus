"""Executor for the update-nautobot-ip step.

All Nautobot work is done by the shared ``DeviceCommonService`` (IPManager): the step resolves the
IP address id and the new values per device, looks up namespace, status and role once per distinct
value, and reports per device. An empty field is left unchanged.
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
from models.failure import FailureInfo
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.nautobot.common.exceptions import NautobotNotFoundError
from services.nautobot.common.validators import is_valid_uuid
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.devices.common import DeviceCommonService
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER
from workflow_steps.common.nautobot_prefix_lookup import LookupFailure, find_containing_prefix
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.partial_outcomes import (
    device_error_from_exception,
    fail_device_with_error,
)
from workflow_steps.common.update_field_expression import resolve_update_field_expression

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "update-nautobot-ip"
_OUTCOME_NAMES = ("success", "failure")
_IP_CONTENT_TYPE = "ipam.ipaddress"
_CONCURRENCY = 5
# Order of the fields in the request and in the first-failure message.
_FIELDS = ("namespace", "type", "role", "status", "dns_name", "description")
_IP_TYPES = ("host", "dhcp", "slaac")


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    ip_id_expression: str
    expressions: dict[str, str]


@dataclass(frozen=True)
class _Bound:
    common: DeviceCommonService
    client: CredentialsBoundNautobotClient


def _text(config: dict[str, Any], key: str) -> str:
    return str(config.get(key) or "").strip()


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    source_id = _text(config, "nautobot_source_id")
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is not configured")
    ip_id_expression = _text(config, "ip_id")
    if not ip_id_expression:
        raise ValueError(f"{_STEP_ID}: ip_id is not configured")
    expressions = {field: _text(config, field) for field in _FIELDS}
    if not any(expressions.values()):
        raise ValueError(
            f"{_STEP_ID}: configure at least one field to update ({', '.join(_FIELDS)})"
        )
    return _ParsedConfig(source_id, ip_id_expression, expressions)


def _bind_nautobot(run: WorkflowRun, source_id: str) -> _Bound:
    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")
    credentials = resolve_nautobot_credentials(db, source_id, step_id=_STEP_ID)
    client = CredentialsBoundNautobotClient(service_factory.get_nautobot_app_service(), credentials)
    return _Bound(DeviceCommonService(client), client)


def _not_found_failure() -> FailureInfo:
    return FailureInfo(phase="api", kind="not_found", hint="check_request")


def _bad_request_failure() -> FailureInfo:
    return FailureInfo(phase="config", kind="bad_request", hint="check_request")


def _failed(
    device: DeviceContext, *, node_id: str, code: str, message: str, failure: FailureInfo
) -> DeviceContext:
    error = DeviceError(
        node_id=node_id, step_id=_STEP_ID, code=code, message=message, failure=failure
    )
    return fail_device_with_error(device, error)


@dataclass(frozen=True)
class _Plan:
    """One device's resolved values.

    ``values`` holds the fields sent as they are; the namespace is separate because Nautobot
    ignores it on an existing address: the step moves the address to a prefix of that namespace.
    """

    device: DeviceContext
    ip_id: str
    values: dict[str, str]
    namespace: str | None = None


def _plan_device(
    parsed: _ParsedConfig, device: DeviceContext, run_id: str
) -> _Plan | tuple[str, str, FailureInfo]:
    """A ``_Plan``, or ``(code, message, failure)`` when the device cannot be updated."""

    def resolve(field: str, raw: str) -> str | None:
        # reveal_secrets=False: the values are copied into a Nautobot request and error text.
        return resolve_update_field_expression(
            device=device, field_key=field, raw_value=raw, run_id=run_id, reveal_secrets=False
        )

    resolved: dict[str, str] = {}
    for field, raw in (("ip_id", parsed.ip_id_expression), *parsed.expressions.items()):
        if not raw:
            continue
        value = resolve(field, raw)
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
        resolved[field] = value.strip()

    # The value is not echoed: it can come from an attribute and ends up in the stored error.
    ip_id = resolved.pop("ip_id", "")
    if not is_valid_uuid(ip_id.lower()):
        return "ip_id_invalid", "ip_id is not a Nautobot UUID", _bad_request_failure()
    values = {field: value for field, value in resolved.items() if value}
    namespace = values.pop("namespace", None)
    if "type" in values:
        ip_type = values["type"].lower()
        if ip_type not in _IP_TYPES:
            return (
                "type_invalid",
                f"type must be one of {', '.join(_IP_TYPES)}",
                _bad_request_failure(),
            )
        values["type"] = ip_type
    if not values and namespace is None:
        return "nothing_to_update", "Every field resolved to an empty value", _bad_request_failure()
    return _Plan(device=device, ip_id=ip_id, values=values, namespace=namespace)


async def _role_id(common: DeviceCommonService, name: str) -> str:
    role_id = await common.resolve_role_id_for_content_type(name, _IP_CONTENT_TYPE)
    if role_id is None:
        raise ValueError(_LOOKUP_MESSAGES["role_not_found"])
    return role_id


async def _status_id(common: DeviceCommonService, name: str) -> str:
    return await common.resolve_status_id(name, content_type=_IP_CONTENT_TYPE)


# The looked-up name is never repeated: it can come from a device attribute.
_LOOKUP_MESSAGES = {
    "namespace_not_found": "The namespace was not found in Nautobot",
    "role_not_found": "The role was not found for IP addresses in Nautobot",
    "status_not_found": "The status was not found for IP addresses in Nautobot",
}

# field -> (error code, resolver turning a name into the id Nautobot expects)
_LOOKUPS: dict[str, tuple[str, Callable[[DeviceCommonService, str], Awaitable[str]]]] = {
    "namespace": ("namespace_not_found", lambda common, name: common.resolve_namespace_id(name)),
    "role": ("role_not_found", _role_id),
    "status": ("status_not_found", _status_id),
}


async def _resolve_ids(
    common: DeviceCommonService, plan: _Plan, cache: dict[tuple[str, str], str | Exception]
) -> _Plan | tuple[str, Exception]:
    """Replace namespace/role/status names by ids; each distinct name is looked up once."""
    values = dict(plan.values)
    namespace = plan.namespace
    for field, (code, resolver) in _LOOKUPS.items():
        name = namespace if field == "namespace" else values.get(field)
        if name is None:
            continue
        key = (field, name)
        if key not in cache:
            try:
                cache[key] = await resolver(common, name)
            except Exception as exc:
                cache[key] = exc
        found = cache[key]
        if isinstance(found, Exception):
            return code, found
        if field == "namespace":
            namespace = found
        else:
            values[field] = found
    return _Plan(plan.device, plan.ip_id, values, namespace)


def _lookup_error(code: str, exc: Exception, node_id: str, device: DeviceContext) -> DeviceContext:
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


def _parent_finder(
    client: CredentialsBoundNautobotClient, namespace_id: str
) -> Callable[[str], Awaitable[str]]:
    """Lookup of the most specific prefix of the target namespace that holds a host address."""

    async def rest_get(endpoint: str) -> Any:
        return await client.rest_request(endpoint=endpoint, method="GET")

    async def find_parent(host: str) -> str:
        prefix_id, _ = await find_containing_prefix(
            rest_get, host, namespace_id, namespace_label="the target namespace"
        )
        return prefix_id

    return find_parent


async def _update(bound: _Bound, plan: _Plan, node_id: str) -> tuple[str, DeviceContext, bool]:
    device = plan.device
    find_parent = _parent_finder(bound.client, plan.namespace) if plan.namespace else None
    try:
        changed = await bound.common.update_ip_address(
            plan.ip_id, plan.values, find_parent=find_parent
        )
    except LookupFailure as exc:
        return (
            "failure",
            _failed(device, node_id=node_id, code=exc.code, message=str(exc), failure=exc.failure),
            False,
        )
    except NautobotNotFoundError:
        return (
            "failure",
            _failed(
                device,
                node_id=node_id,
                code="ip_not_found",
                message="The IP address was not found in Nautobot",
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
    metadata = {**context.metadata, f"{node_id}.update_ip_counts": counts}
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
    common = bound.common
    logger.info(
        "update-nautobot-ip started run_id=%s node_id=%s devices=%d",
        context.run_id,
        node_id,
        len(context.devices),
    )

    results: dict[str, tuple[str, DeviceContext]] = {}
    ready: list[_Plan] = []
    cache: dict[tuple[str, str], str | Exception] = {}
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
        resolved = await _resolve_ids(common, planned, cache)
        if isinstance(resolved, tuple):
            code, exc = resolved
            results[device.id] = ("failure", _lookup_error(code, exc, node_id, device))
        else:
            ready.append(resolved)

    gate = asyncio.Semaphore(_CONCURRENCY)

    async def run_one(plan: _Plan) -> tuple[str, DeviceContext, bool]:
        async with gate:
            return await _update(bound, plan, node_id)

    done = await asyncio.gather(*[run_one(plan) for plan in ready])
    updated = 0
    for plan, (bucket, device, changed) in zip(ready, done, strict=True):
        results[plan.device.id] = (bucket, device)
        updated += int(changed)

    for device_id in context.devices:
        bucket, device = results[device_id]
        buckets[bucket][device_id] = device

    logger.info(
        "update-nautobot-ip finished success=%d failure=%d updated=%d run_id=%s",
        len(buckets["success"]),
        len(buckets["failure"]),
        updated,
        context.run_id,
    )
    return _build_outcomes(context=context, node_id=node_id, buckets=buckets, updated=updated)

"""Executor for the add-ip-to-nautobot step.

All Nautobot work is done by the shared ``DeviceCommonService`` (IPManager / PrefixManager): the
step only decides the address to create, resolves the namespace and status, and reports per device.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
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
from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.devices.common import DeviceCommonService
from workflow_steps.add_ip_to_nautobot.config import get_config
from workflow_steps.common.attribute_write import set_device_attribute
from workflow_steps.common.nautobot_prefix_lookup import LookupFailure, find_containing_prefix
from workflow_steps.common.nautobot_resolve import resolve_nautobot_device_id
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.partial_outcomes import (
    device_error_from_exception,
    fail_device_with_error,
)
from workflow_steps.common.step_flags import parse_bool_flag, parse_int_flag
from workflow_steps.common.update_field_expression import resolve_update_field_expression

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "add-ip-to-nautobot"
_OUTCOME_NAMES = ("success", "failure")
_IP_CONTENT_TYPE = "ipam.ipaddress"
_CONCURRENCY = 5
_DEFAULT_MASK = {4: 24, 6: 64}


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    ip_expression: str
    namespace_expression: str
    status_expression: str
    create_prefix: bool
    default_mask_length: int | None
    description_expression: str
    dns_name_expression: str
    result_attribute: str
    interface_expression: str
    set_primary: bool


@dataclass(frozen=True)
class _Bound:
    common: DeviceCommonService
    client: CredentialsBoundNautobotClient
    service: NautobotService
    credentials: NautobotCredentials


def _text(config: dict[str, Any], key: str) -> str:
    return str(config.get(key) or "").strip()


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    defaults = get_config()
    source_id = _text(config, "nautobot_source_id")
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is not configured")
    ip_expression = _text(config, "ip_address")
    if not ip_expression:
        raise ValueError(f"{_STEP_ID}: ip_address is not configured")

    result_attribute = _text(config, "result_attribute")
    if result_attribute:
        probe = DeviceContext(id="probe", name="probe", hostname="probe")
        try:
            set_device_attribute(probe, result_attribute, "")
        except ValueError as exc:
            raise ValueError(f"{_STEP_ID}: result_attribute {result_attribute!r}: {exc}") from exc

    interface_expression = _text(config, "interface_name")
    set_primary = parse_bool_flag(config, "set_primary", default=False)
    if set_primary and not interface_expression:
        raise ValueError(f"{_STEP_ID}: set_primary needs interface_name")

    mask = parse_int_flag(config, "default_mask_length", default=0, minimum=0, maximum=128)
    return _ParsedConfig(
        source_id=source_id,
        ip_expression=ip_expression,
        namespace_expression=_text(config, "namespace") or defaults["namespace"],
        status_expression=_text(config, "status") or defaults["status"],
        create_prefix=parse_bool_flag(config, "create_prefix", default=False),
        default_mask_length=mask or None,
        description_expression=_text(config, "description"),
        dns_name_expression=_text(config, "dns_name"),
        result_attribute=result_attribute,
        interface_expression=interface_expression,
        set_primary=set_primary,
    )


def _bind_nautobot(run: WorkflowRun, source_id: str) -> _Bound:
    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")
    credentials = resolve_nautobot_credentials(db, source_id, step_id=_STEP_ID)
    service = service_factory.get_nautobot_app_service()
    client = CredentialsBoundNautobotClient(service, credentials)
    return _Bound(DeviceCommonService(client), client, service, credentials)


def _failed(
    device: DeviceContext,
    *,
    node_id: str,
    code: str,
    message: str,
    failure: FailureInfo | None = None,
) -> DeviceContext:
    error = DeviceError(
        node_id=node_id, step_id=_STEP_ID, code=code, message=message, failure=failure
    )
    return fail_device_with_error(device, error)


def _not_found_failure() -> FailureInfo:
    return FailureInfo(phase="api", kind="not_found", hint="check_request")


@dataclass(frozen=True)
class _Plan:
    """One device's resolved settings."""

    device: DeviceContext
    ip_text: str
    namespace: str
    status: str
    description: str
    dns_name: str
    interface: str


def _plan_device(
    parsed: _ParsedConfig, device: DeviceContext, run_id: str
) -> _Plan | tuple[str, str]:
    """A ``_Plan``, or ``(code, message)`` when an expression resolves to nothing."""

    def resolve(field: str, raw: str) -> str | None:
        return resolve_update_field_expression(
            device=device, field_key=field, raw_value=raw, run_id=run_id
        )

    required = (
        ("ip_address", parsed.ip_expression, "ip_unresolved"),
        ("namespace", parsed.namespace_expression, "namespace_unresolved"),
        ("status", parsed.status_expression, "status_unresolved"),
    )
    values: dict[str, str] = {}
    for field, raw, code in required:
        value = resolve(field, raw)
        if not value:
            return code, f"{field} expression {raw!r} resolved to nothing"
        values[field] = value
    optional = {
        "description": resolve("description", parsed.description_expression)
        if parsed.description_expression
        else "",
        "dns_name": resolve("dns_name", parsed.dns_name_expression)
        if parsed.dns_name_expression
        else "",
        "interface": resolve("interface_name", parsed.interface_expression)
        if parsed.interface_expression
        else "",
    }
    if parsed.interface_expression and not optional["interface"]:
        return (
            "interface_unresolved",
            f"interface_name expression {parsed.interface_expression!r} resolved to nothing",
        )
    return _Plan(
        device=device,
        ip_text=values["ip_address"],
        namespace=values["namespace"],
        status=values["status"],
        description=optional["description"] or "",
        dns_name=optional["dns_name"] or "",
        interface=optional["interface"] or "",
    )


async def _full_address(
    parsed: _ParsedConfig, bound: _Bound, plan: _Plan, namespace_id: str
) -> str:
    """``address/mask``: the value's own mask, the containing prefix's, or the default."""
    text = plan.ip_text.strip()
    if "/" in text:
        try:
            return str(ipaddress.ip_interface(text))
        except ValueError as exc:
            raise LookupFailure(
                "ip_invalid",
                f"{text!r} is not a valid IP address",
                FailureInfo(phase="config", kind="bad_request", hint="check_request"),
            ) from exc
    try:
        host = ipaddress.ip_address(text)
    except ValueError as exc:
        raise LookupFailure(
            "ip_invalid",
            f"{text!r} is not a valid IP address",
            FailureInfo(phase="config", kind="bad_request", hint="check_request"),
        ) from exc

    async def rest_get(endpoint: str) -> Any:
        return await bound.client.rest_request(endpoint=endpoint, method="GET")

    try:
        _, prefix = await find_containing_prefix(
            rest_get, str(host), namespace_id, namespace_label=plan.namespace
        )
        return f"{host}/{ipaddress.ip_network(prefix, strict=False).prefixlen}"
    except LookupFailure as exc:
        if exc.code != "prefix_not_found" or not parsed.create_prefix:
            raise
    mask = parsed.default_mask_length or _DEFAULT_MASK[host.version]
    return f"{host}/{mask}"


def _is_missing_prefix(exc: Exception) -> bool:
    return "No suitable parent prefix" in str(exc)


async def _attach(
    parsed: _ParsedConfig, bound: _Bound, plan: _Plan, ip_id: str
) -> tuple[str, str] | None:
    """Assign the IP to the interface (and as primary); ``(code, message)`` on a problem."""
    device_id = await resolve_nautobot_device_id(
        nautobot_service=bound.service, credentials=bound.credentials, device=plan.device
    )
    if device_id is None:
        return "device_not_in_nautobot", "The device was not found in Nautobot"
    interface_id = await bound.common.resolve_interface_by_name(device_id, plan.interface)
    if interface_id is None:
        return "interface_not_found", f"Interface {plan.interface!r} not found on the device"
    await bound.common.assign_ip_to_interface(ip_id, interface_id, False)
    if parsed.set_primary and not await bound.common.assign_primary_ip_to_device(device_id, ip_id):
        return "primary_ip_failed", "Nautobot did not accept the primary IPv4 assignment"
    return None


async def _process(
    *,
    parsed: _ParsedConfig,
    bound: _Bound,
    plan: _Plan,
    namespace_id: str,
    status_id: str,
    node_id: str,
) -> tuple[str, DeviceContext]:
    device = plan.device
    try:
        address = await _full_address(parsed, bound, plan, namespace_id)
        extras = {
            key: value
            for key, value in (("description", plan.description), ("dns_name", plan.dns_name))
            if value
        }
        ip_id = await bound.common.ensure_ip_address_exists(
            address,
            namespace_id,
            status_id,
            add_prefixes_automatically=parsed.create_prefix,
            use_assigned_ip_if_exists=True,
            **extras,
        )
    except LookupFailure as exc:
        return "failure", _failed(
            device, node_id=node_id, code=exc.code, message=str(exc), failure=exc.failure
        )
    except Exception as exc:
        if _is_missing_prefix(exc):
            return "failure", _failed(
                device,
                node_id=node_id,
                code="prefix_not_found",
                message="No parent prefix exists for the address; enable create_prefix",
                failure=_not_found_failure(),
            )
        error = device_error_from_exception(exc, node_id=node_id, step_id=_STEP_ID)
        return "failure", fail_device_with_error(device, error)

    if parsed.result_attribute:
        device = set_device_attribute(device, parsed.result_attribute, ip_id)

    if plan.interface:
        try:
            problem = await _attach(parsed, bound, plan, ip_id)
        except Exception as exc:
            error = device_error_from_exception(exc, node_id=node_id, step_id=_STEP_ID)
            return "failure", fail_device_with_error(device, error)
        if problem is not None:
            code, message = problem
            return "failure", _failed(
                device,
                node_id=node_id,
                code=code,
                message=f"{message} (the IP address {ip_id} was created)",
                failure=_not_found_failure(),
            )
    return "success", device


async def _resolve_cached(
    cache: dict[str, str | Exception], key: str, resolver: Any, *args: Any
) -> str | Exception:
    if key not in cache:
        try:
            cache[key] = await resolver(key, *args)
        except Exception as exc:
            cache[key] = exc
    return cache[key]


def _lookup_error(exc: Exception, code: str, node_id: str, device: DeviceContext) -> DeviceContext:
    if isinstance(exc, ValueError):
        return _failed(
            device,
            node_id=node_id,
            code=code,
            message=str(exc),
            failure=_not_found_failure(),
        )
    return fail_device_with_error(
        device, device_error_from_exception(exc, node_id=node_id, step_id=_STEP_ID)
    )


def _build_outcomes(
    *,
    context: WorkflowContext,
    node_id: str,
    buckets: dict[str, dict[str, DeviceContext]],
) -> list[StepOutcome]:
    counts = {name: len(buckets[name]) for name in _OUTCOME_NAMES}
    metadata = {**context.metadata, f"{node_id}.add_ip_counts": counts}
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
        return _build_outcomes(context=context, node_id=node_id, buckets=buckets)

    bound = _bind_nautobot(run, parsed.source_id)
    logger.info(
        "add-ip-to-nautobot started run_id=%s node_id=%s devices=%d",
        context.run_id,
        node_id,
        len(context.devices),
    )

    results: dict[str, tuple[str, DeviceContext]] = {}
    plans: list[_Plan] = []
    for device in context.devices.values():
        planned = _plan_device(parsed, device, context.run_id)
        if isinstance(planned, tuple):
            code, message = planned
            results[device.id] = (
                "failure",
                _failed(device, node_id=node_id, code=code, message=message),
            )
        else:
            plans.append(planned)

    # Namespace and status are usually the same for every device: resolve each value once.
    namespaces: dict[str, str | Exception] = {}
    statuses: dict[str, str | Exception] = {}
    ready: list[tuple[_Plan, str, str]] = []
    for plan in plans:
        namespace_id = await _resolve_cached(
            namespaces, plan.namespace, bound.common.resolve_namespace_id
        )
        status_id = await _resolve_cached(
            statuses,
            plan.status,
            lambda name: bound.common.resolve_status_id(name, content_type=_IP_CONTENT_TYPE),
        )
        if isinstance(namespace_id, Exception):
            results[plan.device.id] = (
                "failure",
                _lookup_error(namespace_id, "namespace_not_found", node_id, plan.device),
            )
        elif isinstance(status_id, Exception):
            results[plan.device.id] = (
                "failure",
                _lookup_error(status_id, "status_not_found", node_id, plan.device),
            )
        else:
            ready.append((plan, namespace_id, status_id))

    gate = asyncio.Semaphore(_CONCURRENCY)

    async def run_one(plan: _Plan, namespace_id: str, status_id: str) -> tuple[str, DeviceContext]:
        async with gate:
            return await _process(
                parsed=parsed,
                bound=bound,
                plan=plan,
                namespace_id=namespace_id,
                status_id=status_id,
                node_id=node_id,
            )

    done = await asyncio.gather(*[run_one(p, n, s) for p, n, s in ready])
    for (plan, _, _), outcome in zip(ready, done, strict=True):
        results[plan.device.id] = outcome

    for device_id in context.devices:
        bucket, updated = results[device_id]
        buckets[bucket][device_id] = updated

    logger.info(
        "add-ip-to-nautobot finished success=%d failure=%d run_id=%s",
        len(buckets["success"]),
        len(buckets["failure"]),
        context.run_id,
    )
    return _build_outcomes(context=context, node_id=node_id, buckets=buckets)

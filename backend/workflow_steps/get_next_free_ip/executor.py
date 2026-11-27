"""Executor for the get-next-free-ip step."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NamedTuple

from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    DeviceContext,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.nautobot.common.exceptions import (
    NautobotAmbiguousMatchError,
    NautobotInvalidResponseError,
    NautobotNotFoundError,
)
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.devices.common import DeviceCommonService
from workflow_steps.common.attribute_write import set_device_attribute
from workflow_steps.common.device_outcomes import fail_device_with_error, outcomes_from_buckets
from workflow_steps.common.nautobot_plan_fields import (
    PlanError,
    ambiguous_failure,
    bad_request_failure,
    failed,
    not_found_failure,
    resolve_field,
)
from workflow_steps.common.nautobot_prefix_lookup import not_found
from workflow_steps.common.nautobot_step import bind_nautobot_client
from workflow_steps.common.partial_outcomes import (
    NAUTOBOT_TEXT,
    device_error_from_exception,
)
from workflow_steps.common.step_flags import parse_int_flag
from workflow_steps.get_next_free_ip.config import get_config
from workflow_steps.get_next_free_ip.lookup import (
    AVAILABLE_IPS_CAP,
    LookupFailure,
    resolve_containing_prefix,
)
from workflow_steps.get_next_free_ip.pool import (
    bare_address,
    free_addresses_from,
    parse_prefix,
    take,
    window_size,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "get-next-free-ip"
_OUTCOME_NAMES = ("success", "failure")
_MAX_COUNT = 100


class _GroupKey(NamedTuple):
    """(namespace, prefix) as the devices resolved them."""

    namespace: str
    prefix: str


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    prefix_expression: str
    namespace_expression: str
    count: int
    start_offset: int
    attribute_path: str


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    defaults = get_config()
    source_id = str(config.get("nautobot_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is not configured")

    prefix_expression = str(config.get("prefix") or "").strip()
    if not prefix_expression:
        raise ValueError(f"{_STEP_ID}: prefix is not configured")

    attribute_path = str(config.get("attribute_path") or "").strip()
    if not attribute_path:
        raise ValueError(f"{_STEP_ID}: attribute_path is not configured")
    # Fail on an unwritable path (reserved bag, read-only device field) before any lookup.
    try:
        probe = DeviceContext(id="probe", name="probe", hostname="probe")
        set_device_attribute(probe, attribute_path, "")
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: attribute_path {attribute_path!r}: {exc}") from exc

    namespace_expression = str(config.get("namespace") or defaults["namespace"]).strip()
    return _ParsedConfig(
        source_id=source_id,
        prefix_expression=prefix_expression,
        namespace_expression=namespace_expression or defaults["namespace"],
        count=parse_int_flag(
            config, "count", default=defaults["count"], minimum=1, maximum=_MAX_COUNT
        ),
        start_offset=parse_int_flag(
            config, "start_offset", default=defaults["start_offset"], minimum=0
        ),
        attribute_path=attribute_path,
    )


@dataclass(frozen=True)
class _Bound:
    common: DeviceCommonService
    client: CredentialsBoundNautobotClient


def _bind_nautobot(run: WorkflowRun, source_id: str) -> _Bound:
    client = bind_nautobot_client(run, source_id, step_id=_STEP_ID)
    return _Bound(DeviceCommonService(client), client)


async def _resolve_namespace(bound: _Bound, namespace: str) -> str:
    """The namespace UUID (a UUID is used as it is); several matches or none fail the device."""
    try:
        return await bound.common.resolve_namespace_id(namespace)
    except NautobotAmbiguousMatchError as exc:
        raise LookupFailure(
            "namespace_ambiguous",
            f"Namespace {namespace!r} matches more than one namespace in Nautobot",
            ambiguous_failure(),
        ) from exc
    except ValueError as exc:
        raise LookupFailure(
            "namespace_not_found",
            f"Namespace {namespace!r} not found in Nautobot",
            not_found_failure(),
        ) from exc


def _invalid_response(exc: NautobotInvalidResponseError) -> LookupFailure:
    return LookupFailure(
        "invalid_response", str(exc), FailureInfo(phase="api", kind="invalid_response")
    )


async def _resolve_prefix_id(bound: _Bound, prefix: str, namespace_id: str, label: str) -> str:
    """The one prefix UUID in the namespace; none, several or a malformed answer fail."""
    try:
        return await bound.common.resolve_prefix_id(prefix, namespace_id)
    except NautobotNotFoundError as exc:
        raise not_found(
            "prefix_not_found", f"Prefix {prefix} not found in namespace {label!r}"
        ) from exc
    except NautobotAmbiguousMatchError as exc:
        raise LookupFailure(
            "prefix_ambiguous",
            f"Prefix {prefix} matches several prefixes in namespace {label!r}",
            FailureInfo(phase="api", kind="ambiguous_match", hint="check_request"),
        ) from exc
    except NautobotInvalidResponseError as exc:
        raise _invalid_response(exc) from exc


async def _available_ips(bound: _Bound, prefix_id: str, *, limit: int) -> list[Any]:
    try:
        return await bound.common.available_ips(prefix_id, limit=limit)
    except NautobotInvalidResponseError as exc:
        raise _invalid_response(exc) from exc


def _resolve_group_key(
    parsed: _ParsedConfig, device: DeviceContext, run_id: str
) -> _GroupKey | PlanError:
    """``(namespace, prefix)`` as the device resolves them, or the plan error for the device.

    Both go into Nautobot queries and into error text, so a value taken from a secret is refused
    (W5-04) like in the sibling steps (``resolve_field``).
    """
    resolved: list[str] = []
    for field, raw in (
        ("namespace", parsed.namespace_expression),
        ("prefix", parsed.prefix_expression),
    ):
        value = resolve_field(device, run_id, field, raw)
        if isinstance(value, tuple):
            return value
        if not value:
            return (
                f"{field}_unresolved",
                f"{field} expression {raw!r} resolved to nothing",
                bad_request_failure(),
            )
        resolved.append(value)
    return _GroupKey(*resolved)


@dataclass(frozen=True)
class _Target:
    """A prefix found in Nautobot; every raw (namespace, prefix) spelling of it shares one."""

    prefix_id: str
    network: Any
    label: str


async def _resolve_target(
    *,
    key: _GroupKey,
    expression: str,
    bound: _Bound,
) -> _Target:
    namespace, prefix = key
    host = bare_address(prefix)
    try:
        network = None if host is not None else parse_prefix(prefix)
    except ValueError as exc:
        raise LookupFailure(
            "prefix_invalid",
            f"{exc} (prefix setting {expression!r})",
            FailureInfo(phase="config", kind="bad_request", hint="check_request"),
        ) from exc
    namespace_id = await _resolve_namespace(bound, namespace)
    if host is not None:
        # A device address has no prefix length: use the most specific prefix that holds it.
        prefix_id, found = await resolve_containing_prefix(
            bound.client, str(host), namespace_id, namespace_label=namespace
        )
        network = parse_prefix(found)
    else:
        prefix_id = await _resolve_prefix_id(bound, str(network), namespace_id, namespace)
    return _Target(
        prefix_id=prefix_id, network=network, label=f"{network} (namespace {namespace!r})"
    )


async def _load_pool(
    *,
    parsed: _ParsedConfig,
    target: _Target,
    devices: int,
    bound: _Bound,
) -> tuple[list[str], bool]:
    """Free addresses at/after the start offset, and whether the fetch window was cut short.

    The window is cut short when more addresses were wanted than Nautobot is asked for in one
    request and the answer filled it: a shortage is then not proof that the prefix is full.
    """
    wanted = window_size(parsed.start_offset, parsed.count, devices, cap=AVAILABLE_IPS_CAP * 1000)
    limit = min(wanted, AVAILABLE_IPS_CAP)
    available = await _available_ips(bound, target.prefix_id, limit=limit)
    window_cut = wanted > AVAILABLE_IPS_CAP and len(available) >= AVAILABLE_IPS_CAP
    return free_addresses_from(available, target.network, parsed.start_offset), window_cut


def _assign(parsed: _ParsedConfig, device: DeviceContext, addresses: list[str]) -> DeviceContext:
    value: str | list[str] = addresses[0] if parsed.count == 1 else addresses
    return set_device_attribute(device, parsed.attribute_path, value)


def _fail_all(
    members: list[DeviceContext], node_id: str, exc: Exception
) -> dict[str, tuple[str, DeviceContext]]:
    if isinstance(exc, LookupFailure):
        return {
            d.id: (
                "failure",
                failed(
                    _STEP_ID,
                    d,
                    node_id=node_id,
                    code=exc.code,
                    message=str(exc),
                    failure=exc.failure,
                ),
            )
            for d in members
        }
    error = device_error_from_exception(
        exc, node_id=node_id, step_id=_STEP_ID, keep_text=NAUTOBOT_TEXT
    )
    return {d.id: ("failure", fail_device_with_error(d, error)) for d in members}


async def _serve_group(
    *,
    parsed: _ParsedConfig,
    target: _Target,
    members: list[DeviceContext],
    node_id: str,
    bound: _Bound,
) -> dict[str, tuple[str, DeviceContext]]:
    """Bucket every device that uses one prefix, handing out addresses in device order."""
    try:
        pool, window_cut = await _load_pool(
            parsed=parsed,
            target=target,
            devices=len(members),
            bound=bound,
        )
    except Exception as exc:
        return _fail_all(members, node_id, exc)

    results: dict[str, tuple[str, DeviceContext]] = {}
    used = 0
    for device in members:
        chunk = take(pool, used, parsed.count)
        if chunk is None:
            code = "free_ip_window_exceeded" if window_cut else "not_enough_free_ips"
            reason = (
                f"only the first {AVAILABLE_IPS_CAP} free addresses can be read per request "
                "(lower start_offset, count or the number of devices)"
                if window_cut
                else f"{len(pool) - used} left"
            )
            results[device.id] = (
                "failure",
                failed(
                    _STEP_ID,
                    device,
                    node_id=node_id,
                    code=code,
                    message=(
                        f"Needed {parsed.count} free IP(s) in {target.label} "
                        f"from offset {parsed.start_offset}, {reason}"
                    ),
                    failure=FailureInfo(phase="api", kind="not_found", hint="check_request"),
                ),
            )
            continue
        used += parsed.count
        results[device.id] = ("success", _assign(parsed, device, chunk))
    return results


def _counts(node_id: str, buckets: dict[str, dict[str, DeviceContext]]) -> dict[str, Any]:
    return {f"{node_id}.free_ip_counts": {name: len(devices) for name, devices in buckets.items()}}


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
        return outcomes_from_buckets(context, buckets, metadata=_counts(node_id, buckets))

    bound = _bind_nautobot(run, parsed.source_id)
    logger.info(
        "get-next-free-ip started run_id=%s node_id=%s devices=%d count=%d start_offset=%d",
        context.run_id,
        node_id,
        len(context.devices),
        parsed.count,
        parsed.start_offset,
    )

    keyed: list[tuple[_GroupKey, DeviceContext]] = []
    outcome_by_device: dict[str, tuple[str, DeviceContext]] = {}
    for device in context.devices.values():
        key = _resolve_group_key(parsed, device, context.run_id)
        if not isinstance(key, _GroupKey):
            code, message, failure = key
            outcome_by_device[device.id] = (
                "failure",
                failed(
                    _STEP_ID, device, node_id=node_id, code=code, message=message, failure=failure
                ),
            )
            continue
        keyed.append((key, device))

    # Several spellings of one prefix ("2001:DB8::/64" / "2001:db8::/64", "Global" / its UUID)
    # are one prefix in Nautobot: resolve each spelling once, then group by the prefix id so
    # every device of that prefix is served from the same list.
    targets: dict[_GroupKey, _Target | Exception] = {}
    for key, _device in keyed:
        if key not in targets:
            try:
                targets[key] = await _resolve_target(
                    key=key,
                    expression=parsed.prefix_expression,
                    bound=bound,
                )
            except Exception as exc:
                targets[key] = exc

    groups: dict[str, tuple[_Target, list[DeviceContext]]] = {}
    for key, device in keyed:
        target = targets[key]
        if isinstance(target, Exception):
            outcome_by_device.update(_fail_all([device], node_id, target))
            continue
        groups.setdefault(target.prefix_id, (target, []))[1].append(device)

    # Sequential: the free list of a prefix is read once and handed out in device order.
    for target, members in groups.values():
        outcome_by_device.update(
            await _serve_group(
                parsed=parsed,
                target=target,
                members=members,
                node_id=node_id,
                bound=bound,
            )
        )

    for device_id in context.devices:
        bucket, updated = outcome_by_device[device_id]
        buckets[bucket][device_id] = updated

    logger.info(
        "get-next-free-ip finished success=%d failure=%d run_id=%s",
        len(buckets["success"]),
        len(buckets["failure"]),
        context.run_id,
    )
    return outcomes_from_buckets(context, buckets, metadata=_counts(node_id, buckets))

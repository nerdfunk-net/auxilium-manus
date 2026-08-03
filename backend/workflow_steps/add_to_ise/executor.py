"""Executor for the add-to-ise step.

Creates a new ``NetworkDevice`` entry in Cisco ISE for each device in the
workflow context, with an IPv4 address, an optional set of network device
group memberships, and a TACACS+ shared secret. ``device_name``,
``ip_address``, and ``new_key`` each accept either a fixed value or a
``{path.to.value}`` expression resolved per device against the device's
attribute bags (see ``workflow_steps.common.update_field_expression``), the
same convention ``update-ise-tacacs-key`` uses for ``new_key``.

Outcomes: a per-device miss (an unresolved expression, or ISE rejecting the
create — e.g. a duplicate device name) marks that device
``DeviceStatus.FAILED`` but the step itself still emits ``"success"`` — a
"proceed with survivors" step, mirroring ``update-ise-tacacs-key``. The step
emits ``"failure"`` instead only when ISE itself couldn't be reached or
authentication failed (a pre-flight ``test_connection()`` check, and any bare
``ISEAPIError`` raised mid-run) — a condition that affects every device
equally.

``connectModeOptions`` is hardcoded to ``"OFF"`` (matching
``backend/scripts/ise_test.py``'s default) rather than exposed as
configuration, keeping the config surface to the fields the user asked for.

``ip_address`` may resolve to a CIDR-suffixed value (e.g. ``10.0.0.1/24``,
the format Nautobot's ``primary_ip4`` is commonly stored/templated in) —
ISE's ``NetworkDeviceIPList.ipaddress`` field rejects a CIDR suffix outright
with a ``400 Illegal IP Address`` error. The resolved value is normalized to
its bare host address before being sent, and the netmask is always sent as
``/32`` (a single host entry, matching ``backend/scripts/ise_test.py``'s
default) — there is no separate netmask configuration field.

When the default ``{primary_ip4}`` expression is used, ``device.primary_ip4``
is only populated by inventory steps that fetch full device records (Get from
Nautobot, Get from Git). A device sourced via Get from List/Get from ISE and
enriched only by Get Nautobot Attributes never gets that scalar field set —
the IP lives nested at ``nautobot.primary_ip4.address`` instead. ``{primary_ip4}``
falls back to that nested path automatically, mirroring
``get_ise_tacacs_key.executor._effective_primary_ip4``.
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

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
from services.ise.common.exceptions import ISEAPIError, ISEValidationError
from services.ise.source_config_service import ISESourceNotFoundError
from services.workflow_context.attribute_path import resolve_device_value
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.common.update_field_expression import resolve_update_field_expression

if TYPE_CHECKING:
    from services.ise.network_device_service import ISENetworkDeviceService
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "add-to-ise"


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    raw_device_name: str
    raw_ip_address: str
    raw_new_key: str
    description: str
    device_groups: list[str]


@dataclass(frozen=True)
class _ResolvedFields:
    name: str
    ip_host: str
    key: str


@dataclass(frozen=True)
class _CreateOneResult:
    kind: Literal["created", "failed", "abort"]
    device: DeviceContext | None = None
    abort_outcome: StepOutcome | None = None


def _mark_failed(device: DeviceContext, *, node_id: str, code: str, message: str) -> DeviceContext:
    logger.warning("%s: device '%s' failed (%s): %s", _STEP_ID, device.name, code, message)
    error = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, error]}
    )


_HOST_MASK = 32


def _parse_device_groups(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{_STEP_ID}: device_groups must be a list")
    return [str(item).strip() for item in raw if str(item).strip()]


def _extract_ip_host(raw: str) -> str | None:
    """Return the bare host address for a resolved ``ip_address`` value.

    Accepts either a plain address (``10.0.0.1``) or a CIDR-suffixed one
    (``10.0.0.1/24``) and returns ``None`` if the host portion isn't a valid
    IPv4/IPv6 address.
    """
    candidate = raw.split("/", 1)[0].strip()
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return candidate


def _effective_primary_ip4(device: DeviceContext) -> str | None:
    """Resolve a device's primary IPv4 the same way ``get-ise-tacacs-key`` does.

    Prefers the top-level ``primary_ip4`` scalar (set by Get from Nautobot/Get
    from Git); falls back to the ``nautobot`` attribute bag, which is the only
    place the IP lives when a device came from Get from List/Get from ISE and
    was later enriched by a Get Nautobot Attributes step.
    """
    if device.primary_ip4:
        return device.primary_ip4
    value = resolve_device_value(device, "nautobot.primary_ip4.address")
    return str(value) if value else None


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    source_id = (config.get("ise_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: ise_source_id is not configured")

    raw_device_name = (config.get("device_name") or "").strip()
    if not raw_device_name:
        raise ValueError(f"{_STEP_ID}: device_name is not configured")

    raw_ip_address = (config.get("ip_address") or "").strip()
    if not raw_ip_address:
        raise ValueError(f"{_STEP_ID}: ip_address is not configured")

    raw_new_key = (config.get("new_key") or "").strip()
    if not raw_new_key:
        raise ValueError(f"{_STEP_ID}: new_key is not configured")

    description = str(config.get("description") or "").strip()
    device_groups = _parse_device_groups(config.get("device_groups"))

    return _ParsedConfig(
        source_id=source_id,
        raw_device_name=raw_device_name,
        raw_ip_address=raw_ip_address,
        raw_new_key=raw_new_key,
        description=description,
        device_groups=device_groups,
    )


def _build_ise_device_service(run: WorkflowRun, source_id: str) -> ISENetworkDeviceService:
    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    source_config_service = service_factory.build_ise_source_config_service(db)
    try:
        credentials = source_config_service.resolve_credentials(source_id)
    except ISESourceNotFoundError as exc:
        raise ValueError(f"{_STEP_ID}: ISE source '{source_id}' not found") from exc
    except ISEValidationError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc

    return service_factory.build_ise_network_device_service(credentials)


def _resolve_device_fields(
    device: DeviceContext,
    cfg: _ParsedConfig,
    run_id: str | None,
) -> _ResolvedFields | tuple[str, str]:
    """Return resolved fields or ``(failure_code, failure_message)``."""
    resolved_name = resolve_update_field_expression(
        device=device,
        field_key="device_name",
        raw_value=cfg.raw_device_name,
        run_id=run_id,
    )
    if not resolved_name:
        return (
            "device_name_unresolved",
            (
                f"device_name expression '{cfg.raw_device_name}' did not resolve to a "
                f"value for '{device.name}'"
            ),
        )

    resolved_ip = resolve_update_field_expression(
        device=device,
        field_key="ip_address",
        raw_value=cfg.raw_ip_address,
        run_id=run_id,
    )
    if not resolved_ip and "primary_ip4" in cfg.raw_ip_address:
        resolved_ip = _effective_primary_ip4(device)

    if not resolved_ip:
        return (
            "ip_address_unresolved",
            (
                f"ip_address expression '{cfg.raw_ip_address}' did not resolve to a "
                f"value for '{device.name}' (device.primary_ip4={device.primary_ip4!r}, "
                f"available attribute bags: {sorted(device.attribute_bags)})"
            ),
        )

    ip_host = _extract_ip_host(resolved_ip)
    if not ip_host:
        return (
            "ip_address_invalid",
            (
                f"ip_address resolved to '{resolved_ip}' for '{device.name}', which is "
                "not a valid IP address"
            ),
        )

    resolved_key = resolve_update_field_expression(
        device=device,
        field_key="new_key",
        raw_value=cfg.raw_new_key,
        run_id=run_id,
    )
    if not resolved_key:
        return (
            "tacacs_key_unresolved",
            (
                f"new_key expression '{cfg.raw_new_key}' did not resolve to a value for "
                f"'{device.name}' (available attribute bags: {sorted(device.attribute_bags)})"
            ),
        )

    return _ResolvedFields(name=resolved_name, ip_host=ip_host, key=resolved_key)


def _build_create_payload(
    resolved: _ResolvedFields,
    *,
    description: str,
    device_groups: list[str],
) -> dict[str, Any]:
    device_payload: dict[str, Any] = {
        "name": resolved.name,
        "NetworkDeviceIPList": [{"ipaddress": resolved.ip_host, "mask": _HOST_MASK}],
        "tacacsSettings": {"sharedSecret": resolved.key, "connectModeOptions": "OFF"},
    }
    if description:
        device_payload["description"] = description
    if device_groups:
        device_payload["NetworkDeviceGroupList"] = device_groups
    return device_payload


def _enrich_device_after_create(
    device: DeviceContext,
    device_payload: dict[str, Any],
    created: dict[str, Any],
    resolved_key: str,
) -> DeviceContext:
    sealed_ise_payload = {
        **device_payload,
        "tacacsSettings": {
            **device_payload["tacacsSettings"],
            "sharedSecret": seal_secret(resolved_key),
        },
    }
    attribute_bags = {
        **device.attribute_bags,
        "ise": {**sealed_ise_payload, "id": created.get("id"), "is_group_or_prefix": False},
        "tacacs": {"shared_secret": seal_secret(resolved_key)},
    }
    return device.model_copy(
        update={
            "attribute_bags": attribute_bags,
            "capabilities": device.capabilities | {Capability.ATTRIBUTES},
        }
    )


async def _create_one_device(
    *,
    device_id: str,
    device: DeviceContext,
    cfg: _ParsedConfig,
    device_service: ISENetworkDeviceService,
    source_id: str,
    node_id: str,
    context: WorkflowContext,
) -> _CreateOneResult:
    resolved = _resolve_device_fields(device, cfg, context.run_id)
    if isinstance(resolved, tuple):
        failure_code, failure_message = resolved
        return _CreateOneResult(
            kind="failed",
            device=_mark_failed(
                device,
                node_id=node_id,
                code=failure_code,
                message=failure_message,
            ),
        )

    device_payload = _build_create_payload(
        resolved,
        description=cfg.description,
        device_groups=cfg.device_groups,
    )

    try:
        created = await device_service.create_device(device_payload)
    except ISEValidationError as exc:
        return _CreateOneResult(
            kind="failed",
            device=_mark_failed(
                device,
                node_id=node_id,
                code="ise_device_create_rejected",
                message=f"ISE rejected creating device '{resolved.name}': {exc}",
            ),
        )
    except ISEAPIError as exc:
        logger.warning(
            "%s: lost connection to ISE source '%s' while creating device '%s': %s",
            _STEP_ID,
            source_id,
            resolved.name,
            exc,
        )
        return _CreateOneResult(
            kind="abort",
            abort_outcome=StepOutcome(
                name="failure",
                context=context,
                summary=f"lost connection to ISE source '{source_id}': {exc}",
            ),
        )

    updated = _enrich_device_after_create(device, device_payload, created, resolved.key)
    logger.info("%s: created device=%s ise_id=%s", _STEP_ID, resolved.name, created.get("id"))
    return _CreateOneResult(kind="created", device=updated)


def _build_success_outcome(
    *,
    context: WorkflowContext,
    updated_devices: dict[str, DeviceContext],
    node_id: str,
    created_count: int,
    failed_count: int,
) -> StepOutcome:
    metadata = {
        **context.metadata,
        f"{node_id}.total": len(context.devices),
        f"{node_id}.created_count": created_count,
        f"{node_id}.failed_count": failed_count,
    }

    if failed_count:
        logger.warning(
            "%s: %d/%d device(s) failed for node_id=%s — see the per-device warnings above "
            "for the reason each one failed",
            _STEP_ID,
            failed_count,
            len(context.devices),
            node_id,
        )

    logger.info(
        "%s finished node_id=%s created=%d failed=%d run_id=%s",
        _STEP_ID,
        node_id,
        created_count,
        failed_count,
        context.run_id,
    )

    return StepOutcome(
        name="success",
        context=context.model_copy(update={"devices": updated_devices, "metadata": metadata}),
        summary=f"created {created_count}, failed {failed_count}",
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
    del artifact_service  # unused for this step

    parsed = _parse_config(config)

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    device_service = _build_ise_device_service(run, parsed.source_id)

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d",
        _STEP_ID,
        context.run_id,
        node_id,
        len(context.devices),
    )

    try:
        await device_service.test_connection()
    except ISEAPIError as exc:
        logger.warning("%s: could not reach ISE source '%s': %s", _STEP_ID, parsed.source_id, exc)
        return [
            StepOutcome(
                name="failure",
                context=context,
                summary=f"could not reach ISE source '{parsed.source_id}': {exc}",
            )
        ]

    updated_devices: dict[str, DeviceContext] = {}
    created_count = 0
    failed_count = 0

    for device_id, device in context.devices.items():
        result = await _create_one_device(
            device_id=device_id,
            device=device,
            cfg=parsed,
            device_service=device_service,
            source_id=parsed.source_id,
            node_id=node_id,
            context=context,
        )

        if result.kind == "abort":
            assert result.abort_outcome is not None
            return [result.abort_outcome]

        assert result.device is not None
        if result.kind == "failed":
            updated_devices[device_id] = result.device
            failed_count += 1
            continue

        updated_devices[device_id] = result.device
        created_count += 1

    return [
        _build_success_outcome(
            context=context,
            updated_devices=updated_devices,
            node_id=node_id,
            created_count=created_count,
            failed_count=failed_count,
        )
    ]

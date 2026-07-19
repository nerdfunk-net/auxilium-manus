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
from typing import Any

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
from workflow_steps.common.attribute_path import resolve_device_value
from workflow_steps.common.update_field_expression import resolve_update_field_expression

logger = logging.getLogger(__name__)

_STEP_ID = "add-to-ise"


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


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    del artifact_service  # unused for this step

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

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

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

    device_service = service_factory.build_ise_network_device_service(credentials)

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
        logger.warning("%s: could not reach ISE source '%s': %s", _STEP_ID, source_id, exc)
        return [
            StepOutcome(
                name="failure",
                context=context,
                summary=f"could not reach ISE source '{source_id}': {exc}",
            )
        ]

    updated_devices: dict[str, DeviceContext] = {}
    created_count = 0
    failed_count = 0

    for device_id, device in context.devices.items():
        resolved_name = resolve_update_field_expression(
            device=device,
            field_key="device_name",
            raw_value=raw_device_name,
            run_id=context.run_id,
        )
        if not resolved_name:
            updated_devices[device_id] = _mark_failed(
                device,
                node_id=node_id,
                code="device_name_unresolved",
                message=(
                    f"device_name expression '{raw_device_name}' did not resolve to a "
                    f"value for '{device.name}'"
                ),
            )
            failed_count += 1
            continue

        resolved_ip = resolve_update_field_expression(
            device=device,
            field_key="ip_address",
            raw_value=raw_ip_address,
            run_id=context.run_id,
        )
        if not resolved_ip and "primary_ip4" in raw_ip_address:
            resolved_ip = _effective_primary_ip4(device)

        if not resolved_ip:
            updated_devices[device_id] = _mark_failed(
                device,
                node_id=node_id,
                code="ip_address_unresolved",
                message=(
                    f"ip_address expression '{raw_ip_address}' did not resolve to a "
                    f"value for '{device.name}' (device.primary_ip4={device.primary_ip4!r}, "
                    f"available attribute bags: {sorted(device.attribute_bags)})"
                ),
            )
            failed_count += 1
            continue

        ip_host = _extract_ip_host(resolved_ip)
        if not ip_host:
            updated_devices[device_id] = _mark_failed(
                device,
                node_id=node_id,
                code="ip_address_invalid",
                message=(
                    f"ip_address resolved to '{resolved_ip}' for '{device.name}', which is "
                    "not a valid IP address"
                ),
            )
            failed_count += 1
            continue

        resolved_key = resolve_update_field_expression(
            device=device,
            field_key="new_key",
            raw_value=raw_new_key,
            run_id=context.run_id,
        )
        if not resolved_key:
            updated_devices[device_id] = _mark_failed(
                device,
                node_id=node_id,
                code="tacacs_key_unresolved",
                message=(
                    f"new_key expression '{raw_new_key}' did not resolve to a value for "
                    f"'{device.name}' (available attribute bags: {sorted(device.attribute_bags)})"
                ),
            )
            failed_count += 1
            continue

        device_payload: dict[str, Any] = {
            "name": resolved_name,
            "NetworkDeviceIPList": [{"ipaddress": ip_host, "mask": _HOST_MASK}],
            "tacacsSettings": {"sharedSecret": resolved_key, "connectModeOptions": "OFF"},
        }
        if description:
            device_payload["description"] = description
        if device_groups:
            device_payload["NetworkDeviceGroupList"] = device_groups

        try:
            created = await device_service.create_device(device_payload)
        except ISEValidationError as exc:
            updated_devices[device_id] = _mark_failed(
                device,
                node_id=node_id,
                code="ise_device_create_rejected",
                message=f"ISE rejected creating device '{resolved_name}': {exc}",
            )
            failed_count += 1
            continue
        except ISEAPIError as exc:
            logger.warning(
                "%s: lost connection to ISE source '%s' while creating device '%s': %s",
                _STEP_ID,
                source_id,
                resolved_name,
                exc,
            )
            return [
                StepOutcome(
                    name="failure",
                    context=context,
                    summary=f"lost connection to ISE source '{source_id}': {exc}",
                )
            ]

        attribute_bags = {
            **device.attribute_bags,
            "ise": {**device_payload, "id": created.get("id"), "is_group_or_prefix": False},
            "tacacs": {"shared_secret": resolved_key},
        }
        updated_devices[device_id] = device.model_copy(
            update={
                "attribute_bags": attribute_bags,
                "capabilities": device.capabilities | {Capability.ATTRIBUTES},
            }
        )
        created_count += 1
        logger.info("%s: created device=%s ise_id=%s", _STEP_ID, resolved_name, created.get("id"))

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

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": updated_devices, "metadata": metadata}),
            summary=f"created {created_count}, failed {failed_count}",
        )
    ]

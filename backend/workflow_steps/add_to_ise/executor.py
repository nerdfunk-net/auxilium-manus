"""Executor for the add-to-ise step.

Creates a new ``NetworkDevice`` entry in Cisco ISE for each device in the
workflow context, with an IPv4 address, an optional set of network device
group memberships, and a TACACS+ shared secret. ``device_name``,
``description``, ``ip_address``, ``new_key`` and each ``device_groups`` entry
accept either a fixed value or a ``{path.to.value}`` expression resolved per
device against the device's attribute bags (see
``workflow_steps.common.update_field_expression``), the same convention
``update-ise-tacacs-key`` uses for ``new_key``.

A ``device_groups`` expression must resolve to an *existing* attribute: a
missing/null one fails the device (``device_group_unresolved``), while one that
exists but is blank adds no group for that entry.

``create_missing_groups`` (default off): when enabled, every resolved
``device_groups`` entry that does not yet exist in ISE is created (with any
missing ancestors, see ``group_ensure``) before the device is created; a group
that cannot be created fails the device (``ise_device_group_create_failed``).
When off, ISE's own "NDG cannot be found" rejection fails the device.

Outcomes: devices are routed per outcome handle.

* ``"success"`` — devices that were created.
* ``"exists"`` — devices ISE refused to create because a network device with
  that name already exists. They are passed through unchanged (not failed).
* ``"failure"`` — devices that could not be created, each marked
  ``DeviceStatus.FAILED`` with a ``DeviceError``: an unresolved expression, or
  ISE rejecting the create for any reason other than a duplicate name. It also
  carries the whole input context when the step itself broke: ISE couldn't be
  reached or authentication failed (a pre-flight ``test_connection()`` check,
  and any bare ``ISEAPIError`` raised mid-run), which affects every device
  equally.

Debugging: every device for which a create request was actually sent gets a
``RequestRecord`` in ``DeviceContext.requests[node_id]`` — the exact
``NetworkDevice`` body posted to ISE (after ``{path}`` resolution) and ISE's
response (or the error ISE returned). It is recorded for created,
already-existing and rejected devices alike, with the TACACS+ shared secret
redacted, and is shown in the run's device detail view only — it is not an
attribute bag, so other steps and ``{path}`` expressions never see it.
Devices that failed before a request was built (unresolved expressions) have
none.

``single_connect_mode`` sets ISE's ``tacacsSettings.connectModeOptions`` (the
"Enable Single Connect Mode" checkbox): ``OFF`` (default, unchecked),
``ON_LEGACY`` (Legacy Cisco Device) or ``ON_DRAFT_COMPLIANT`` (TACACS Draft
Compliance Single Connect Support). It is a fixed choice, not a ``{path}``
expression; any other value raises ``ValueError``.

``ip_address`` may resolve to a CIDR-suffixed value (e.g. ``10.0.0.1/24``,
the format Nautobot's ``primary_ip4`` is commonly stored/templated in) —
ISE's ``NetworkDeviceIPList.ipaddress`` field rejects a CIDR suffix outright
with a ``400 Illegal IP Address`` error. The resolved value is therefore split
into the bare host address (``ipaddress``) and a separate ``mask``. The mask
is, in order of precedence: the optional ``netmask_override`` config value
(e.g. ``32`` or ``/32``), the suffix of the resolved ``ip_address``, else
``/32`` (a single host entry, matching ``backend/scripts/ise_test.py``).

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
from services.ise.credentials import ISECredentials
from services.ise.source_config_service import ISESourceNotFoundError
from services.workflow_context.attribute_path import resolve_device_value
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.add_to_ise.group_ensure import DeviceGroupEnsurer
from workflow_steps.common.request_record import append_request_record
from workflow_steps.common.update_field_expression import (
    resolve_expression_if_present,
    resolve_update_field_expression,
)

if TYPE_CHECKING:
    from services.ise.network_device_service import ISENetworkDeviceService
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "add-to-ise"
# Fragment of the ISE ERS 400 message for a duplicate device name
# ("Network Device Create failed: Device Name Already Exists"). Matched
# case-insensitively and loosely so minor wording changes across ISE versions
# still route to the "exists" outcome.
_ALREADY_EXISTS_MARKER = "already exist"
_ISE_CREATE_ENDPOINT = "/ers/config/networkdevice"
_CONNECT_MODE_OFF = "OFF"
_CONNECT_MODES = frozenset({_CONNECT_MODE_OFF, "ON_LEGACY", "ON_DRAFT_COMPLIANT"})


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    raw_device_name: str
    raw_ip_address: str
    raw_new_key: str
    description: str
    device_groups: list[str]
    netmask_override: int | None = None
    create_missing_groups: bool = False
    single_connect_mode: str = _CONNECT_MODE_OFF


@dataclass(frozen=True)
class _ResolvedFields:
    name: str
    ip_host: str
    mask: int
    key: str
    description: str
    device_groups: list[str]
    single_connect_mode: str = _CONNECT_MODE_OFF


@dataclass(frozen=True)
class _CreateOneResult:
    kind: Literal["created", "exists", "failed", "abort"]
    device: DeviceContext | None = None
    abort_outcome: StepOutcome | None = None


def _mark_failed(device: DeviceContext, *, node_id: str, code: str, message: str) -> DeviceContext:
    logger.warning("%s: device '%s' failed (%s): %s", _STEP_ID, device.name, code, message)
    error = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, error]}
    )


_HOST_MASK = 32
_MAX_MASK_BY_VERSION = {4: 32, 6: 128}


def _parse_device_groups(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{_STEP_ID}: device_groups must be a list")
    return [str(item).strip() for item in raw if str(item).strip()]


def _parse_single_connect_mode(raw: Any) -> str:
    """Validate the ``single_connect_mode`` config value; blank means ``OFF``."""
    mode = str(raw or "").strip() or _CONNECT_MODE_OFF
    if mode not in _CONNECT_MODES:
        raise ValueError(
            f"{_STEP_ID}: single_connect_mode must be one of {sorted(_CONNECT_MODES)}, got '{raw}'"
        )
    return mode


def _parse_netmask_override(raw: Any) -> int | None:
    """Parse the optional ``netmask_override`` config value (``"32"``, ``"/32"``, ``32``)."""
    if raw is None:
        return None
    text = str(raw).strip().lstrip("/").strip()
    if not text:
        return None
    if not text.isdigit() or int(text) > _MAX_MASK_BY_VERSION[6]:
        raise ValueError(
            f"{_STEP_ID}: netmask_override must be a prefix length such as 32 or /24, got '{raw}'"
        )
    return int(text)


def _extract_ip_mask(raw: str, ip_host: str, override: int | None) -> int | None:
    """Pick the mask for *ip_host*: override, else the ``/nn`` suffix of *raw*, else /32.

    Returns ``None`` when the chosen mask is not valid for the address family.
    """
    mask = override
    if mask is None:
        _, _, suffix = raw.partition("/")
        suffix = suffix.strip()
        if suffix:
            if not suffix.isdigit():
                return None
            mask = int(suffix)
    if mask is None:
        mask = _HOST_MASK
    if mask > _MAX_MASK_BY_VERSION[ipaddress.ip_address(ip_host).version]:
        return None
    return mask


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

    netmask_override = _parse_netmask_override(config.get("netmask_override"))

    return _ParsedConfig(
        source_id=source_id,
        raw_device_name=raw_device_name,
        raw_ip_address=raw_ip_address,
        raw_new_key=raw_new_key,
        description=description,
        device_groups=device_groups,
        netmask_override=netmask_override,
        create_missing_groups=config.get("create_missing_groups") is True,
        single_connect_mode=_parse_single_connect_mode(config.get("single_connect_mode")),
    )


def _resolve_source_credentials(run: WorkflowRun, source_id: str) -> ISECredentials:
    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    source_config_service = service_factory.build_ise_source_config_service(db)
    try:
        return source_config_service.resolve_credentials(source_id)
    except ISESourceNotFoundError as exc:
        raise ValueError(f"{_STEP_ID}: ISE source '{source_id}' not found") from exc
    except ISEValidationError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc


def _build_ise_device_service(run: WorkflowRun, source_id: str) -> ISENetworkDeviceService:
    return service_factory.build_ise_network_device_service(
        _resolve_source_credentials(run, source_id)
    )


def _build_group_ensurer(run: WorkflowRun, source_id: str) -> DeviceGroupEnsurer:
    group_service = service_factory.build_ise_network_device_group_service(
        _resolve_source_credentials(run, source_id)
    )
    return DeviceGroupEnsurer(group_service)


def _resolve_device_groups(
    device: DeviceContext, raw_groups: list[str]
) -> list[str] | tuple[str, str]:
    """Resolve each ``device_groups`` entry, or return ``(failure_code, message)``.

    An entry whose ``{path}`` does not exist for the device fails it; one that
    exists but is blank contributes no group (ISE then applies its default root).
    """
    resolved: list[str] = []
    for raw in raw_groups:
        found, value = resolve_expression_if_present(device=device, raw_value=raw)
        if not found:
            return (
                "device_group_unresolved",
                (
                    f"device_groups entry '{raw}' did not resolve for '{device.name}' "
                    f"(available attribute bags: {sorted(device.attribute_bags)})"
                ),
            )
        if value:
            resolved.append(value)
    return resolved


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

    mask = _extract_ip_mask(resolved_ip, ip_host, cfg.netmask_override)
    if mask is None:
        return (
            "netmask_invalid",
            (
                f"netmask for '{resolved_ip}' on '{device.name}' is not a valid prefix length "
                f"(netmask_override={cfg.netmask_override!r})"
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

    # description is optional: an expression that resolves to nothing just
    # leaves the ISE description empty instead of failing the device.
    resolved_description = resolve_update_field_expression(
        device=device,
        field_key="description",
        raw_value=cfg.description,
        run_id=run_id,
    )
    if cfg.description and not resolved_description:
        logger.warning(
            "%s: description expression '%s' did not resolve for '%s'; creating without one",
            _STEP_ID,
            cfg.description,
            device.name,
        )

    resolved_groups = _resolve_device_groups(device, cfg.device_groups)
    if isinstance(resolved_groups, tuple):
        return resolved_groups

    return _ResolvedFields(
        name=resolved_name,
        ip_host=ip_host,
        mask=mask,
        key=resolved_key,
        description=resolved_description or "",
        device_groups=resolved_groups,
        single_connect_mode=cfg.single_connect_mode,
    )


def _build_create_payload(resolved: _ResolvedFields) -> dict[str, Any]:
    device_payload: dict[str, Any] = {
        "name": resolved.name,
        "NetworkDeviceIPList": [{"ipaddress": resolved.ip_host, "mask": resolved.mask}],
        "tacacsSettings": {
            "sharedSecret": resolved.key,
            "connectModeOptions": resolved.single_connect_mode,
        },
    }
    if resolved.description:
        device_payload["description"] = resolved.description
    if resolved.device_groups:
        device_payload["NetworkDeviceGroupList"] = resolved.device_groups
    return device_payload


def _sealed_payload(device_payload: dict[str, Any], resolved_key: str) -> dict[str, Any]:
    return {
        **device_payload,
        "tacacsSettings": {
            **device_payload["tacacsSettings"],
            "sharedSecret": seal_secret(resolved_key),
        },
    }


def _with_request_record(
    device: DeviceContext,
    *,
    node_id: str,
    device_payload: dict[str, Any],
    resolved_key: str,
    response: dict[str, Any],
    ok: bool,
) -> DeviceContext:
    """Record the create request and ISE's response for the detail view.

    The shared secret is sealed first so the marker-based redaction in
    ``append_request_record`` replaces it — no key material is stored.
    """
    return append_request_record(
        device,
        node_id=node_id,
        target="Cisco ISE",
        method="POST",
        endpoint=_ISE_CREATE_ENDPOINT,
        request={"NetworkDevice": _sealed_payload(device_payload, resolved_key)},
        response=response,
        ok=ok,
    )


def _enrich_device_after_create(
    device: DeviceContext,
    device_payload: dict[str, Any],
    created: dict[str, Any],
    resolved_key: str,
    node_id: str,
) -> DeviceContext:
    sealed_ise_payload = _sealed_payload(device_payload, resolved_key)
    attribute_bags = {
        **device.attribute_bags,
        "ise": {**sealed_ise_payload, "id": created.get("id"), "is_group_or_prefix": False},
        "tacacs": {"shared_secret": seal_secret(resolved_key)},
    }
    enriched = device.model_copy(
        update={
            "attribute_bags": attribute_bags,
            "capabilities": device.capabilities | {Capability.ATTRIBUTES},
        }
    )
    return _with_request_record(
        enriched,
        node_id=node_id,
        device_payload=device_payload,
        resolved_key=resolved_key,
        response=created,
        ok=True,
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
    group_ensurer: DeviceGroupEnsurer | None = None,
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

    device_payload = _build_create_payload(resolved)

    try:
        if group_ensurer is not None:
            for group_name in resolved.device_groups:
                await group_ensurer.ensure(group_name)
    except ISEValidationError as exc:
        return _CreateOneResult(
            kind="failed",
            device=_mark_failed(
                device,
                node_id=node_id,
                code="ise_device_group_create_failed",
                message=f"could not create missing device group for '{resolved.name}': {exc}",
            ),
        )
    except ISEAPIError as exc:
        return _CreateOneResult(
            kind="abort",
            abort_outcome=StepOutcome(
                name="failure",
                context=context,
                summary=f"lost connection to ISE source '{source_id}': {exc}",
            ),
        )

    try:
        created = await device_service.create_device(device_payload)
    except ISEValidationError as exc:
        if _ALREADY_EXISTS_MARKER in str(exc).lower():
            logger.info(
                "%s: device '%s' already exists in ISE source '%s': %s",
                _STEP_ID,
                resolved.name,
                source_id,
                exc,
            )
            exists_device = _with_request_record(
                device,
                node_id=node_id,
                device_payload=device_payload,
                resolved_key=resolved.key,
                response={"error": str(exc)},
                ok=False,
            )
            return _CreateOneResult(kind="exists", device=exists_device)
        rejected = _mark_failed(
            device,
            node_id=node_id,
            code="ise_device_create_rejected",
            message=f"ISE rejected creating device '{resolved.name}': {exc}",
        )
        return _CreateOneResult(
            kind="failed",
            device=_with_request_record(
                rejected,
                node_id=node_id,
                device_payload=device_payload,
                resolved_key=resolved.key,
                response={"error": str(exc)},
                ok=False,
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

    updated = _enrich_device_after_create(device, device_payload, created, resolved.key, node_id)
    logger.info("%s: created device=%s ise_id=%s", _STEP_ID, resolved.name, created.get("id"))
    return _CreateOneResult(kind="created", device=updated)


def _build_outcomes(
    *,
    context: WorkflowContext,
    success_devices: dict[str, DeviceContext],
    exists_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
    node_id: str,
) -> list[StepOutcome]:
    created_count = len(success_devices)
    exists_count = len(exists_devices)
    failed_count = len(failed_devices)
    metadata = {
        **context.metadata,
        f"{node_id}.total": len(context.devices),
        f"{node_id}.created_count": created_count,
        f"{node_id}.exists_count": exists_count,
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
        "%s finished node_id=%s created=%d exists=%d failed=%d run_id=%s",
        _STEP_ID,
        node_id,
        created_count,
        exists_count,
        failed_count,
        context.run_id,
    )

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices, "metadata": metadata}),
            summary=f"created {created_count}",
        ),
        StepOutcome(
            name="exists",
            context=context.model_copy(update={"devices": exists_devices, "metadata": metadata}),
            summary=f"already exists {exists_count}",
        ),
        StepOutcome(
            name="failure",
            context=context.model_copy(update={"devices": failed_devices, "metadata": metadata}),
            summary=f"failed {failed_count}",
        ),
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
    del artifact_service  # unused for this step

    parsed = _parse_config(config)

    if not context.devices:
        return [
            StepOutcome(name="success", context=context),
            StepOutcome(name="exists", context=context),
            StepOutcome(name="failure", context=context),
        ]

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

    group_ensurer = (
        _build_group_ensurer(run, parsed.source_id) if parsed.create_missing_groups else None
    )

    success_devices: dict[str, DeviceContext] = {}
    exists_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    for device_id, device in context.devices.items():
        result = await _create_one_device(
            device_id=device_id,
            device=device,
            cfg=parsed,
            device_service=device_service,
            source_id=parsed.source_id,
            node_id=node_id,
            context=context,
            group_ensurer=group_ensurer,
        )

        if result.kind == "abort":
            assert result.abort_outcome is not None  # noqa: S101  # type narrowing on result.kind
            return [result.abort_outcome]

        assert result.device is not None  # noqa: S101  # type narrowing on result.kind
        if result.kind == "exists":
            exists_devices[device_id] = result.device
            continue

        if result.kind == "failed":
            failed_devices[device_id] = result.device
        else:
            success_devices[device_id] = result.device

    return _build_outcomes(
        context=context,
        success_devices=success_devices,
        exists_devices=exists_devices,
        failed_devices=failed_devices,
        node_id=node_id,
    )

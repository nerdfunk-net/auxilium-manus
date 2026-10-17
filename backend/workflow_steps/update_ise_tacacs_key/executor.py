"""Executor for the update-ise-tacacs-key step.

Sets ``tacacsSettings.sharedSecret`` on each device in Cisco ISE. The new key
comes from ``config["new_key"]`` — either a fixed value, or a
``{path.to.value}`` expression resolved per device against the device's
attribute bags (see ``workflow_steps.common.update_field_expression``), the
same convention ``update-nautobot-device`` uses for its field values.

Outcomes (DN-A): only devices that now carry the new key leave through ``"success"``.
A per-device miss (unresolved key expression, device not found in ISE, or ISE rejected
the update) marks that device ``DeviceStatus.FAILED`` and routes it through
``"failure"``. When ISE is lost mid-run, the devices already processed keep their result
and every unprocessed device leaves through ``"failure"`` with the transport cause.
A failed pre-flight ``test_connection()`` check emits ``"failure"`` for all devices.

Device resolution: when a device already came from ISE (``device.source ==
"ise"``, e.g. via Get from ISE), its ``device.id`` is the raw ISE NetworkDevice
id and is used directly. Otherwise the device is looked up by name via
``get_device_by_name`` — a single lookup, not the multi-tier fallback chain
``get-ise-tacacs-key`` uses for reads, since picking the wrong device to write
to is worse than failing closed.

ISE's ERS ``PUT`` replaces the whole ``tacacsSettings`` sub-object if it's
present in the payload at all (``ISENetworkDeviceService.update_device``'s own
merge is only one level deep), so the current ``tacacsSettings`` is fetched
first and only ``sharedSecret`` is overridden before the update call — this
preserves sibling settings such as ``enableKeyWrap``/``connectModeOptions``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.ise.common.exceptions import ISEAPIError, ISENotFoundError, ISEValidationError
from services.ise.network_device_service import ISENetworkDeviceService
from services.ise.source_config_service import ISESourceNotFoundError
from services.workflow_context.secret_expression import require_secret_expression
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.common.attribute_write import set_device_attribute
from workflow_steps.common.partial_outcomes import abort_outcomes
from workflow_steps.common.update_field_expression import resolve_update_field_expression

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "update-ise-tacacs-key"


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    raw_new_key: str


@dataclass(frozen=True)
class _UpdateOneResult:
    kind: Literal["ok", "fail", "abort"]
    device: DeviceContext | None = None
    # "abort" carries the cause; execute() turns it into the partial outcomes (DN-A).
    failure: FailureInfo | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.kind == "ok"


def _mark_failed(
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
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, error]}
    )


async def _resolve_ise_device_id(
    device: DeviceContext, device_service: ISENetworkDeviceService
) -> str | None:
    if device.source == "ise" and device.id:
        return device.id
    try:
        result = await device_service.get_device_by_name(device.name)
    except ISENotFoundError:
        return None
    detail = result.get("NetworkDevice") or {}
    device_id = detail.get("id")
    return str(device_id) if device_id else None


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    source_id = (config.get("ise_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: ise_source_id is not configured")

    raw_new_key = (config.get("new_key") or "").strip()
    if not raw_new_key:
        raise ValueError(f"{_STEP_ID}: new_key is not configured")
    raw_new_key = require_secret_expression(raw_new_key, field="new_key", step_id=_STEP_ID)

    return _ParsedConfig(source_id=source_id, raw_new_key=raw_new_key)


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


async def _preflight_ise(
    device_service: ISENetworkDeviceService,
    source_id: str,
    context: WorkflowContext,
) -> list[StepOutcome] | None:
    try:
        await device_service.test_connection()
    except ISEAPIError as exc:
        logger.warning("%s: could not reach ISE source '%s': %s", _STEP_ID, source_id, exc)
        return [
            StepOutcome(
                name="failure",
                context=context,
                summary=f"could not reach ISE source '{source_id}': {exc}",
                failure=exc.failure,
            )
        ]
    return None


async def _update_one_device(
    *,
    device_id: str,
    device: DeviceContext,
    device_service: ISENetworkDeviceService,
    parsed: _ParsedConfig,
    node_id: str,
    run_id: str | None,
    context: WorkflowContext,
) -> _UpdateOneResult:
    del device_id

    new_key_value = resolve_update_field_expression(
        device=device,
        field_key="new_key",
        raw_value=parsed.raw_new_key,
        run_id=run_id,
    )
    if not new_key_value:
        return _UpdateOneResult(
            kind="fail",
            device=_mark_failed(
                device,
                node_id=node_id,
                code="tacacs_key_unresolved",
                message=f"new_key expression did not resolve to a value for '{device.name}'",
            ),
        )

    try:
        ise_device_id = await _resolve_ise_device_id(device, device_service)
    except ISEAPIError as exc:
        logger.warning(
            "%s: lost connection to ISE source '%s' while resolving device '%s': %s",
            _STEP_ID,
            parsed.source_id,
            device.name,
            exc,
        )
        return _UpdateOneResult(
            kind="abort",
            failure=exc.failure,
            message=f"lost connection to ISE source '{parsed.source_id}'",
        )

    if not ise_device_id:
        return _UpdateOneResult(
            kind="fail",
            device=_mark_failed(
                device,
                node_id=node_id,
                code="ise_device_not_found",
                message=(
                    f"could not locate device '{device.name}' in ISE source '{parsed.source_id}'"
                ),
            ),
        )

    try:
        current = await device_service.get_device(ise_device_id)
        current_tacacs = current.get("NetworkDevice", {}).get("tacacsSettings") or {}
        merged_tacacs = {**current_tacacs, "sharedSecret": new_key_value}
        await device_service.update_device(ise_device_id, {"tacacsSettings": merged_tacacs})
    except (ISENotFoundError, ISEValidationError) as exc:
        return _UpdateOneResult(
            kind="fail",
            device=_mark_failed(
                device,
                node_id=node_id,
                code="tacacs_key_update_rejected",
                message=f"ISE rejected the TACACS+ key update for '{device.name}': {exc}",
                failure=exc.failure,
            ),
        )
    except ISEAPIError as exc:
        logger.warning(
            "%s: lost connection to ISE source '%s' while updating device '%s': %s",
            _STEP_ID,
            parsed.source_id,
            device.name,
            exc,
        )
        return _UpdateOneResult(
            kind="abort",
            failure=exc.failure,
            message=f"lost connection to ISE source '{parsed.source_id}'",
        )

    updated = set_device_attribute(device, "tacacs.shared_secret", seal_secret(new_key_value))
    logger.info("%s: updated tacacs key for device=%s", _STEP_ID, device.name)
    return _UpdateOneResult(kind="ok", device=updated)


def _build_outcomes(
    *,
    context: WorkflowContext,
    node_id: str,
    updated_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
) -> list[StepOutcome]:
    metadata = {
        **context.metadata,
        f"{node_id}.total": len(context.devices),
        f"{node_id}.updated_count": len(updated_devices),
        f"{node_id}.failed_count": len(failed_devices),
    }

    logger.info(
        "%s finished node_id=%s updated=%d failed=%d run_id=%s",
        _STEP_ID,
        node_id,
        len(updated_devices),
        len(failed_devices),
        context.run_id,
    )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": updated_devices, "metadata": metadata}),
            summary=f"updated {len(updated_devices)}, failed {len(failed_devices)}",
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(
                    update={"devices": failed_devices, "metadata": metadata}
                ),
                summary=f"{len(failed_devices)} device(s) not updated",
            )
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

    preflight = await _preflight_ise(device_service, parsed.source_id, context)
    if preflight is not None:
        return preflight

    updated_devices: dict[str, DeviceContext] = {}  # ISE accepted the key
    failed_devices: dict[str, DeviceContext] = {}  # not found / rejected / key unresolved

    for device_id, device in context.devices.items():
        result = await _update_one_device(
            device_id=device_id,
            device=device,
            device_service=device_service,
            parsed=parsed,
            node_id=node_id,
            run_id=context.run_id,
            context=context,
        )
        if result.kind == "abort":
            return abort_outcomes(
                context=context,
                node_id=node_id,
                step_id=_STEP_ID,
                done_ok=updated_devices,
                done_failed=failed_devices,
                message=result.message,
                failure=result.failure,
            )

        assert result.device is not None  # noqa: S101  # type narrowing on result.kind
        (updated_devices if result.ok else failed_devices)[device_id] = result.device

    return _build_outcomes(
        context=context,
        node_id=node_id,
        updated_devices=updated_devices,
        failed_devices=failed_devices,
    )

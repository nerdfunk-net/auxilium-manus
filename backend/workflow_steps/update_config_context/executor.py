"""Executor for the update-config-context workflow step.

Writes, updates, or appends into a Nautobot device's local config context
(``local_config_context_data``). See doc/WORKFLOW-STEPS.md for the step
contract and backend/services/nautobot/devices/update.py for the underlying
REST PATCH semantics (Nautobot replaces this field wholesale — there is no
server-side partial JSON merge, so ``update``/``append`` GET the current
value, compute the new document here, then PATCH the whole thing back).
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.devices.update import DeviceUpdateService
from services.workflow_context.attribute_path import resolve_device_attribute, resolve_device_value
from services.workflow_context.secret_fields import (
    REDACTED_PLACEHOLDER,
    is_sealed_secret,
    unwrap_secret,
)
from workflow_steps.common.attribute_merge import deep_merge_mapping
from workflow_steps.common.jinja_render import build_jinja_context, render_jinja_template
from workflow_steps.common.json_object_path import get_at_path, set_at_path, top_level_key
from workflow_steps.common.nautobot_resolve import resolve_nautobot_device_id
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.template_content import load_stored_template

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "update-config-context"
_MODES = ("write", "update", "append")


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    identifier_mode: str
    device_identifier: dict[str, Any]
    mode: str
    path: str
    value_source_type: str
    attribute_path: str
    template_id: int | None
    create_local_if_missing: bool = False


# Like placeholder_template's pattern but also allows "-" so attribute names such
# as ``custom.tacacs-server`` work inside a path.
_PATH_PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_.\-]+)\}")


def _render_path(path: str, device: DeviceContext | None) -> str:
    """Resolve ``{attribute.path}`` placeholders in *path* for one device.

    Lets a path pick a list item by a per-device attribute, e.g.
    ``tacacs[server={custom.tacacs-server}].key``. A placeholder that resolves
    to nothing fails the device rather than substituting an empty string, which
    could select the wrong list item (or none). The same goes for a secret: a
    sealed value resolves to a redaction placeholder, which must never be
    looked up as if it were data. A resolved value may not contain ``[`` or
    ``]`` — it would break the ``[field=value]`` filter — and outside a filter
    it may not contain ``.``, which would silently add a path level.
    """
    if not _PATH_PLACEHOLDER.search(path):
        return path
    if device is None:
        raise ValueError(
            f"{_STEP_ID}: path placeholders need a workflow device "
            "(use device_identifier.mode = from_context)"
        )

    def _substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        value = resolve_device_attribute(device, key, reveal_secrets=False)
        text = (value or "").strip()
        if not text:
            raise ValueError(
                f"{_STEP_ID}: path placeholder {{{key}}} did not resolve to a value "
                f"for '{device.name}'"
            )
        if text == REDACTED_PLACEHOLDER:
            raise ValueError(
                f"{_STEP_ID}: path placeholder {{{key}}} is a secret for '{device.name}' "
                "and can't be used in a path"
            )
        inside_filter = path[: match.start()].count("[") > path[: match.start()].count("]")
        if "." in text and not inside_filter:
            raise ValueError(
                f"{_STEP_ID}: path placeholder {{{key}}} resolved to a value containing a dot "
                f"for '{device.name}'; outside a [field=value] filter that would add a path level"
            )
        if "[" in text or "]" in text:
            raise ValueError(
                f"{_STEP_ID}: path placeholder {{{key}}} resolved to a value containing "
                f"brackets for '{device.name}', which a path filter can't hold"
            )
        return text

    return _PATH_PLACEHOLDER.sub(_substitute, path)


def _parse_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    source_id = str(config.get("nautobot_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is not configured")

    raw_identifier = config.get("device_identifier") or {}
    if not isinstance(raw_identifier, dict):
        raw_identifier = {}
    identifier_mode = str(raw_identifier.get("mode") or "from_context").strip()

    mode = str(config.get("mode") or "write").strip().lower()
    if mode not in _MODES:
        raise ValueError(f"{_STEP_ID}: mode must be one of {', '.join(_MODES)}")

    path = str(config.get("path") or "").strip()
    if mode == "update" and not path:
        raise ValueError(f"{_STEP_ID}: path is required for mode {mode!r}")

    raw_value_source = config.get("value_source") or {}
    if not isinstance(raw_value_source, dict):
        raise ValueError(f"{_STEP_ID}: value_source must be an object")

    value_source_type = str(raw_value_source.get("type") or "attribute").strip().lower()
    if value_source_type not in ("attribute", "template"):
        raise ValueError(f"{_STEP_ID}: value_source.type must be 'attribute' or 'template'")

    attribute_path = str(raw_value_source.get("attribute_path") or "").strip()
    template_id: int | None = None
    if value_source_type == "attribute":
        if not attribute_path:
            raise ValueError(f"{_STEP_ID}: value_source.attribute_path is required")
    else:
        raw_template_id = raw_value_source.get("template_id")
        if raw_template_id in (None, ""):
            raise ValueError(f"{_STEP_ID}: value_source.template_id is required")
        try:
            template_id = int(raw_template_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{_STEP_ID}: value_source.template_id must be an integer") from exc

    return _ParsedConfig(
        source_id=source_id,
        identifier_mode=identifier_mode,
        device_identifier=raw_identifier,
        mode=mode,
        path=path,
        value_source_type=value_source_type,
        attribute_path=attribute_path,
        template_id=template_id,
        create_local_if_missing=_parse_bool(config.get("create_local_if_missing", False)),
    )


def _resolve_device_items(
    identifier_mode: str, context: WorkflowContext
) -> list[tuple[str, DeviceContext | None]]:
    if identifier_mode == "explicit":
        return [("explicit", None)]
    if not context.devices:
        raise ValueError(
            f"{_STEP_ID}: no devices in workflow context; "
            "connect an inventory step or use an explicit device identifier"
        )
    return list(context.devices.items())


def _explicit_device_context(raw_identifier: dict[str, Any]) -> DeviceContext:
    """Build a placeholder device from an explicit id/name/ip_address so the
    same resolve_nautobot_device_id() path handles both from_context and
    explicit identifier modes."""
    explicit_id = str(raw_identifier.get("id") or "").strip()
    explicit_name = str(raw_identifier.get("name") or "").strip()
    explicit_ip = str(raw_identifier.get("ip_address") or "").strip()
    return DeviceContext(
        id=explicit_id or "explicit",
        name=explicit_name,
        hostname=explicit_name or explicit_id or "explicit",
        source="nautobot",
        primary_ip4=explicit_ip or None,
    )


def _build_update_service(
    db: Any, source_id: str
) -> tuple[NautobotService, NautobotCredentials, DeviceUpdateService]:
    credentials = resolve_nautobot_credentials(db, source_id, step_id=_STEP_ID)
    nautobot_service = service_factory.get_nautobot_app_service()
    bound_client = CredentialsBoundNautobotClient(nautobot_service, credentials)
    return nautobot_service, credentials, DeviceUpdateService(bound_client)


def _resolve_value(
    *,
    parsed: _ParsedConfig,
    device: DeviceContext | None,
    run_id: str | None,
    workflow_id: str | None,
) -> Any:
    if parsed.value_source_type == "attribute":
        if device is None:
            raise ValueError(
                f"{_STEP_ID}: an attribute value source requires a workflow device "
                "(use device_identifier.mode = from_context)"
            )
        raw = resolve_device_value(device, parsed.attribute_path, run_id=run_id)
        if is_sealed_secret(raw):
            raw = unwrap_secret(raw)
        return raw

    template_id = parsed.template_id
    if template_id is None:
        raise ValueError(f"{_STEP_ID}: value_source.template_id is required")
    template_content = load_stored_template(template_id, step_id=_STEP_ID).strip()
    if not template_content:
        raise ValueError(f"{_STEP_ID}: stored template {template_id} has no content")
    jinja_device = device or DeviceContext(id="explicit", name="explicit", hostname="explicit")
    jinja_context = build_jinja_context(jinja_device, run_id=run_id, workflow_id=workflow_id)
    rendered = render_jinja_template(template_content, jinja_context)
    try:
        return json.loads(rendered)
    except (json.JSONDecodeError, ValueError):
        return rendered


async def _seed_from_global(
    *,
    update_service: DeviceUpdateService,
    device_id: str,
    current: dict[str, Any],
    path: str,
) -> dict[str, Any]:
    """Return *current* with the path's top-level key copied in from the device's
    global (merged) config context, when the local context lacks that key.

    Nautobot only lets us write ``local_config_context_data``; a key that lives
    only in an assigned context has to be copied into the local one before part
    of it can be changed. Only that one key is copied, deep so later edits never
    touch the fetched global data. A key absent from the global context too is
    left alone — ``update``/``append`` then create it as they always have.
    """
    key = top_level_key(path)
    if key in current:
        return current
    merged = await update_service.get_config_context(device_id)
    if key not in merged:
        return current
    # Key name only — the value can hold secrets (e.g. TACACS+ keys).
    logger.info(
        "%s: copying %r from the global config context for device %s", _STEP_ID, key, device_id
    )
    return {**current, key: copy.deepcopy(merged[key])}


async def _apply_mode(
    *,
    update_service: DeviceUpdateService,
    device_id: str,
    parsed: _ParsedConfig,
    value: Any,
) -> None:
    if parsed.mode == "write":
        if not isinstance(value, dict):
            raise ValueError(
                f"{_STEP_ID}: resolved value must be a JSON object for mode 'write' "
                f"(got {type(value).__name__})"
            )
        await update_service.set_local_config_context(device_id, value)
        return

    current = await update_service.get_local_config_context(device_id)
    if parsed.create_local_if_missing and parsed.path:
        current = await _seed_from_global(
            update_service=update_service,
            device_id=device_id,
            current=current,
            path=parsed.path,
        )

    if parsed.mode == "update":
        new_document = set_at_path(current, parsed.path, value)
        await update_service.set_local_config_context(device_id, new_document)
        return

    # append with an empty path: merge the value's own top-level keys directly
    # into the document root, never clobber siblings.
    if not parsed.path:
        if not isinstance(value, dict):
            raise ValueError(
                f"{_STEP_ID}: resolved value must be a JSON object for mode 'append' "
                f"with an empty path (got {type(value).__name__})"
            )
        new_document = deep_merge_mapping(current, value, overwrite=True)
        await update_service.set_local_config_context(device_id, new_document)
        return

    # append with a path: merge into an existing object at the path, never
    # clobber siblings.
    existing_leaf = get_at_path(current, parsed.path)
    if isinstance(existing_leaf, dict) and isinstance(value, dict):
        merged = deep_merge_mapping(existing_leaf, value, overwrite=True)
    else:
        merged = value
    new_document = set_at_path(current, parsed.path, merged)
    await update_service.set_local_config_context(device_id, new_document)


def _fail_device(
    *,
    device_key: str,
    device: DeviceContext | None,
    node_id: str,
    code: str | None = None,
    message: str | None = None,
    exc: Exception | None = None,
) -> tuple[str, DeviceContext | None, bool]:
    error_code = code or (type(exc).__name__.lower() if exc is not None else "error")
    error_message = message or (str(exc) if exc is not None else "Unknown error")

    if device is None:
        placeholder = DeviceContext(
            id=device_key,
            name=device_key,
            hostname=device_key,
            source="nautobot",
            status=DeviceStatus.FAILED,
            errors=[
                DeviceError(
                    node_id=node_id, step_id=_STEP_ID, code=error_code, message=error_message
                )
            ],
        )
        return device_key, placeholder, False

    failed = device.model_copy(
        update={
            "status": DeviceStatus.FAILED,
            "errors": [
                *device.errors,
                DeviceError(
                    node_id=node_id, step_id=_STEP_ID, code=error_code, message=error_message
                ),
            ],
        }
    )
    return device_key, failed, False


async def _update_one_device(
    *,
    device_key: str,
    device: DeviceContext | None,
    parsed: _ParsedConfig,
    context: WorkflowContext,
    node_id: str,
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
    update_service: DeviceUpdateService,
) -> tuple[str, DeviceContext | None, bool]:
    try:
        parsed = replace(parsed, path=_render_path(parsed.path, device))
        target = (
            device
            if device is not None
            else _explicit_device_context(parsed.device_identifier)
        )
        nautobot_device_id = await resolve_nautobot_device_id(
            nautobot_service=nautobot_service,
            credentials=credentials,
            device=target,
        )
        if nautobot_device_id is None:
            return _fail_device(
                device_key=device_key,
                device=device,
                node_id=node_id,
                code="not_found",
                message=f"No Nautobot device found for {device_key} "
                f"(name={target.name!r}, ip={target.primary_ip4!r})",
            )

        value = _resolve_value(
            parsed=parsed,
            device=device,
            run_id=str(context.run_id) if context.run_id else None,
            workflow_id=str(context.workflow_id) if context.workflow_id else None,
        )
        await _apply_mode(
            update_service=update_service,
            device_id=nautobot_device_id,
            parsed=parsed,
            value=value,
        )

        if device is None:
            placeholder = DeviceContext(
                id=nautobot_device_id,
                name=target.name or nautobot_device_id,
                hostname=target.name or nautobot_device_id,
                source="nautobot",
                status=DeviceStatus.OK,
            )
            return device_key, placeholder, True

        updated = device.model_copy(update={"status": DeviceStatus.OK})
        return device_key, updated, True
    except Exception as exc:
        return _fail_device(device_key=device_key, device=device, node_id=node_id, exc=exc)


def _build_outcomes(
    context: WorkflowContext,
    success_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
) -> list[StepOutcome]:
    outcomes = [
        StepOutcome(name="success", context=context.model_copy(update={"devices": success_devices}))
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure", context=context.model_copy(update={"devices": failed_devices})
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
    del artifact_service, device_sessions

    parsed = _parse_config(config)

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    nautobot_service, credentials, update_service = _build_update_service(db, parsed.source_id)
    device_items = _resolve_device_items(parsed.identifier_mode, context)

    logger.info(
        "%s started run_id=%s source_id=%s devices=%d mode=%s path=%s",
        _STEP_ID,
        run.id,
        parsed.source_id,
        len(device_items),
        parsed.mode,
        parsed.path or "-",
    )

    results = await asyncio.gather(
        *[
            _update_one_device(
                device_key=device_key,
                device=device,
                parsed=parsed,
                context=context,
                node_id=node_id,
                nautobot_service=nautobot_service,
                credentials=credentials,
                update_service=update_service,
            )
            for device_key, device in device_items
        ]
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    for device_key, updated_device, ok in results:
        if updated_device is None:
            continue
        if ok:
            success_devices[device_key] = updated_device
        else:
            failed_devices[device_key] = updated_device

    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        _STEP_ID,
        len(success_devices),
        len(failed_devices),
        run.id,
    )

    return _build_outcomes(context, success_devices, failed_devices)

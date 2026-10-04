"""TextFSM / Genie normalisation of raw run-command output."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

import service_factory
from models.workflow_context import Capability, DeviceContext
from services.network.pyats.platform import resolve_pyats_os
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from services.pyats.source_config_service import (
    PyATSSourceConfigService,
    PyATSSourceNotFoundError,
)

logger = logging.getLogger(__name__)


def enrich_with_textfsm(
    *,
    success_devices: dict[str, DeviceContext],
    raw_outputs_by_device: dict[str, dict[str, str]],
    parsed_output_key: str,
    run_id: Any,
) -> dict[str, DeviceContext]:
    """Normalize netmiko's TextFSM output into the same inline shape Genie
    enrichment uses (``parsed.<parsed_output_key>.<command> = {"parsed", "error"}``),
    so a downstream step reads structured command output the same way
    regardless of which parser produced it.

    Non-fatal per command, matching Genie: netmiko falls back to returning the
    raw device text unchanged when no TextFSM template matches a command, so
    that command's ``output`` isn't valid JSON here -- record it as an error
    on that one command instead of failing the whole device.
    """
    enriched: dict[str, DeviceContext] = dict(success_devices)
    ok_count = 0
    error_count = 0
    for device_id, device in success_devices.items():
        raw_outputs = raw_outputs_by_device.get(device_id) or {}
        if not raw_outputs:
            continue
        parsed_entry: dict[str, Any] = {}
        for command, output in raw_outputs.items():
            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                parsed_entry[command] = {
                    "parsed": None,
                    "error": "TextFSM did not match this command's output (no template found)",
                }
                error_count += 1
                continue
            parsed_entry[command] = {"parsed": data, "error": None}
            ok_count += 1
        parsed = dict(device.parsed)
        parsed[parsed_output_key] = parsed_entry
        enriched[device_id] = device.model_copy(
            update={
                "parsed": parsed,
                "capabilities": device.capabilities | {Capability.PARSED},
            }
        )

    logger.info(
        "run-command textfsm parsing finished run_id=%s devices=%d commands_ok=%d "
        "commands_error=%d",
        run_id,
        len(enriched),
        ok_count,
        error_count,
    )
    return enriched


async def enrich_with_genie(
    *,
    success_devices: dict[str, DeviceContext],
    raw_outputs_by_device: dict[str, dict[str, str]],
    pyats_source_id: str,
    parsed_output_key: str,
    network_driver_override: str | None,
    db: Session,
    run_id: Any,
) -> dict[str, DeviceContext]:
    """Genie-parse each device's already-fetched raw output via the pyATS shim.

    Non-fatal by design: a device whose raw command execution already
    succeeded must not become FAILED just because Genie infrastructure is
    unreachable or has no parser for a given command -- see "Chosen design"
    in the plan this implements.
    """
    payload: dict[str, dict[str, Any]] = {}
    for device_id, device in success_devices.items():
        raw_outputs = raw_outputs_by_device.get(device_id) or {}
        if not raw_outputs:
            continue
        os_name = resolve_pyats_os(
            network_driver=device.network_driver,
            platform=device.platform,
            override=network_driver_override,
        )
        payload[device_id] = {
            "os": os_name,
            "commands": [
                {"command": command, "output": output} for command, output in raw_outputs.items()
            ],
        }

    if not payload:
        return success_devices

    try:
        credentials = PyATSSourceConfigService(db).resolve_credentials(pyats_source_id)
        shim = service_factory.get_pyats_app_service()
        response = await shim.parse_batch(credentials, devices=payload)
    except (PyATSSourceNotFoundError, PyATSValidationError, PyATSAPIError) as exc:
        logger.warning(
            "run-command genie parsing unavailable, skipping enrichment run_id=%s error=%s",
            run_id,
            exc,
        )
        return success_devices

    raw_results: dict[str, Any] = response.get("results") or {}
    enriched: dict[str, DeviceContext] = dict(success_devices)
    ok_count = 0
    error_count = 0
    for device_id, device_result in raw_results.items():
        device = enriched.get(device_id)
        if device is None:
            continue
        commands = device_result.get("commands") or {}
        parsed_entry: dict[str, Any] = {}
        for command, entry in commands.items():
            parsed_entry[command] = {"parsed": entry.get("parsed"), "error": entry.get("error")}
            if entry.get("error"):
                error_count += 1
            else:
                ok_count += 1
        parsed = dict(device.parsed)
        parsed[parsed_output_key] = parsed_entry
        enriched[device_id] = device.model_copy(
            update={
                "parsed": parsed,
                "capabilities": device.capabilities | {Capability.PARSED},
            }
        )

    logger.info(
        "run-command genie parsing finished run_id=%s devices=%d commands_ok=%d commands_error=%d",
        run_id,
        len(raw_results),
        ok_count,
        error_count,
    )
    return enriched

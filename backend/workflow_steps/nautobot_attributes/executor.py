"""Executor for the get-nautobot-attributes step."""

from __future__ import annotations

import asyncio
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
from repositories.settings_repository import SettingsRepository
from services.artifacts import ArtifactService
from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials
from services.settings.source_keys import build_source_key

logger = logging.getLogger(__name__)

_ATTR_TO_VAR: dict[str, str] = {
    "interfaces": "get_interfaces",
    "custom_fields": "get_custom_fields",
    "tags": "get_tags",
    "config_context": "get_config_context",
    "secret_groups": "get_secret_groups",
    "console_ports": "get_console_port",
    "power_ports": "get_power_port",
}

_DEVICE_FIELDS = """
    id
    name
    hostname: name
    asset_tag
    serial
    position
    face
    config_context @include(if: $get_config_context)
    local_config_context_data @include(if: $get_config_context)
    _custom_field_data @include(if: $get_custom_fields)
    primary_ip4 @include(if: $get_primary_ipv4) {
      id
      address
      description
      ip_version
      host
      mask_length
      dns_name
      status {
        id
        name
      }
      parent {
        id
        prefix
      }
    }
    role {
      id
      name
    }
    device_type {
      id
      model
      manufacturer {
        id
        name
      }
    }
    platform {
      id
      name
      network_driver
      manufacturer {
        id
        name
      }
    }
    location {
      id
      name
      description
      parent {
        id
        name
      }
    }
    status {
      id
      name
    }
    interfaces @include(if: $get_interfaces) {
      id
      name
      type
      enabled
      mtu
      mac_address
      description
      status {
        id
        name
      }
      ip_addresses {
        id
        address
        ip_version
        status {
          id
          name
        }
      }
      connected_interface {
        id
        name
        device {
          id
          name
        }
      }
      cable {
        id
        status {
          id
          name
        }
      }
      tagged_vlans {
        id
        name
        vid
      }
      untagged_vlan {
        id
        name
        vid
      }
    }
    console_ports @include(if: $get_console_port) {
      id
      name
      type
      description
    }
    console_server_ports @include(if: $get_console_port) {
      id
      name
      type
      description
    }
    power_ports @include(if: $get_power_port) {
      id
      name
      type
      description
    }
    power_outlets @include(if: $get_power_port) {
      id
      name
      type
      description
    }
    secrets_group @include(if: $get_secret_groups) {
      id
      name
    }
    tags @include(if: $get_tags) {
      id
      name
      color
    }
"""

_QUERY_VARIABLES = """
  $get_primary_ipv4: Boolean = false,
  $get_interfaces: Boolean = false,
  $get_config_context: Boolean = false,
  $get_custom_fields: Boolean = false,
  $get_tags: Boolean = false,
  $get_secret_groups: Boolean = false,
  $get_console_port: Boolean = false,
  $get_power_port: Boolean = false
"""

_DEVICE_DETAILS_QUERY = (
    "query DeviceDetails(\n  $deviceId: ID!,\n"
    + _QUERY_VARIABLES
    + ") {\n  device(id: $deviceId) {"
    + _DEVICE_FIELDS
    + "  }\n}"
)


async def _fetch_device(
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
    device_id: str,
    variables: dict[str, Any],
) -> dict[str, Any] | None:
    vars_with_id = {"deviceId": device_id, **variables}
    response = await nautobot_service.graphql_query(
        _DEVICE_DETAILS_QUERY, vars_with_id, credentials
    )
    device = (response.get("data") or {}).get("device")
    if device is None:
        logger.warning(
            "get-nautobot-attributes: no device data for id=%s errors=%s",
            device_id,
            response.get("errors"),
        )
    return device


def _attributes_from_detail(detail: dict[str, Any]) -> dict[str, Any]:
    attributes = dict(detail)
    custom_fields = attributes.pop("_custom_field_data", None)
    if custom_fields is not None:
        attributes["custom_fields"] = custom_fields
    return attributes


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    del artifact_service  # unused for this step

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    source_id = config.get("nautobot_source_id", "").strip()
    if not source_id:
        raise ValueError("get-nautobot-attributes: nautobot_source_id is not configured")

    list_of_attributes: list[str] = config.get("list_of_attributes") or []

    db = object_session(run)
    if db is None:
        raise RuntimeError("get-nautobot-attributes: WorkflowRun has no active DB session")

    setting_key = build_source_key("nautobot", source_id)
    setting = SettingsRepository(db).get_by_key(setting_key)
    if setting is None:
        raise ValueError(
            f"get-nautobot-attributes: Nautobot source '{source_id}' not found in settings"
        )

    nautobot_url = (setting.value or {}).get("url", "").strip()
    nautobot_token = (setting.value or {}).get("token", "").strip()
    if not nautobot_url or not nautobot_token:
        raise ValueError(
            f"get-nautobot-attributes: Nautobot source '{source_id}' is missing url or token"
        )

    credentials = service_factory.credentials_from_connection(nautobot_url, nautobot_token)
    nautobot_service = service_factory.get_nautobot_app_service()

    variables: dict[str, Any] = {"get_primary_ipv4": True}
    for attr_key in list_of_attributes:
        var_name = _ATTR_TO_VAR.get(attr_key)
        if var_name:
            variables[var_name] = True

    logger.info(
        "get-nautobot-attributes run_id=%s source_id=%s devices=%d attributes=%s",
        run.id,
        source_id,
        len(context.devices),
        list_of_attributes,
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def enrich_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool]:
        try:
            detail = await _fetch_device(nautobot_service, credentials, device_id, variables)
            if detail is None:
                err = DeviceError(
                    node_id=node_id,
                    step_id="get-nautobot-attributes",
                    code="not_found",
                    message=f"No Nautobot data returned for device {device_id}",
                )
                failed = device.model_copy(
                    update={
                        "status": DeviceStatus.FAILED,
                        "errors": [*device.errors, err],
                    }
                )
                return device_id, failed, False

            platform_raw = detail.get("platform")
            platform = platform_raw if isinstance(platform_raw, dict) else {}
            enriched = device.model_copy(
                update={
                    "attributes": _attributes_from_detail(detail),
                    "platform": platform.get("name") or device.platform,
                    "network_driver": platform.get("network_driver") or device.network_driver,
                    "capabilities": device.capabilities | {Capability.ATTRIBUTES},
                    "status": DeviceStatus.OK,
                }
            )
            return device_id, enriched, True
        except Exception as exc:
            err = DeviceError(
                node_id=node_id,
                step_id="get-nautobot-attributes",
                code=type(exc).__name__.lower(),
                message=str(exc),
            )
            failed = device.model_copy(
                update={
                    "status": DeviceStatus.FAILED,
                    "errors": [*device.errors, err],
                }
            )
            return device_id, failed, False

    results = await asyncio.gather(
        *[enrich_device(device_id, device) for device_id, device in context.devices.items()]
    )

    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    logger.info(
        "get-nautobot-attributes returning %d/%d devices run_id=%s",
        len(success_devices),
        len(context.devices),
        run.id,
    )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed_devices}),
            )
        )
    return outcomes

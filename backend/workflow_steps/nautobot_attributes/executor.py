"""Executor for the get-nautobot-attributes step."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from repositories.settings_repository import SettingsRepository
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

_DEVICE_DETAILS_QUERY = """
query DeviceDetails(
  $deviceId: ID!,
  $get_primary_ipv4: Boolean = false,
  $get_interfaces: Boolean = false,
  $get_config_context: Boolean = false,
  $get_custom_fields: Boolean = false,
  $get_tags: Boolean = false,
  $get_secret_groups: Boolean = false,
  $get_console_port: Boolean = false,
  $get_power_port: Boolean = false
) {
  device(id: $deviceId) {
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
  }
}
"""


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
        errors = response.get("errors")
        logger.warning(
            "get-nautobot-attributes: no device data for id=%s errors=%s",
            device_id,
            errors,
        )
    return device


async def execute(
    *,
    config: dict[str, Any],
    parent_outputs: dict[str, Any],
    run: WorkflowRun,
) -> dict[str, Any]:
    source_id = config.get("nautobot_source_id", "").strip()
    if not source_id:
        raise ValueError("get-nautobot-attributes: nautobot_source_id is not configured")

    list_of_attributes: list[str] = config.get("list_of_attributes") or []

    device_ids: list[str] = []
    for output in parent_outputs.values():
        if isinstance(output, dict) and "device_ids" in output:
            device_ids = output["device_ids"]
            break

    if not device_ids:
        raise ValueError("get-nautobot-attributes: no device_ids found in parent step output")

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
        len(device_ids),
        list_of_attributes,
    )

    tasks = [
        _fetch_device(nautobot_service, credentials, device_id, variables)
        for device_id in device_ids
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    device_details: list[dict[str, Any]] = []
    for device_id, result in zip(device_ids, results):
        if isinstance(result, BaseException):
            logger.error(
                "get-nautobot-attributes: failed to fetch device id=%s error=%s",
                device_id,
                result,
            )
        elif result is not None:
            device_details.append(result)

    logger.info(
        "get-nautobot-attributes returning %d/%d devices run_id=%s",
        len(device_details),
        len(device_ids),
        run.id,
    )

    return {
        "general": {
            "source_id": source_id,
            "total": len(device_details),
        },
        "device_ids": [d["id"] for d in device_details],
        "device_details": device_details,
    }

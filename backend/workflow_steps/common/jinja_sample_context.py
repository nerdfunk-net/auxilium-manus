"""Build Jinja preview contexts from Nautobot or workflow device data."""

from __future__ import annotations

import logging
from typing import Any

import service_factory
from models.workflow_context import Capability, DeviceContext, DeviceStatus
from repositories.settings_repository import SettingsRepository
from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials
from services.settings.source_keys import build_source_key
from sqlalchemy.orm import Session
from workflow_steps.common.jinja_render import build_jinja_context
from workflow_steps.nautobot_attributes.executor import (
    _ATTR_TO_VAR,
    _attributes_from_detail,
    _fetch_device,
)

logger = logging.getLogger(__name__)

_DEVICE_BY_NAME_QUERY = """
query DeviceByName($name: [String!]) {
  devices(name: $name) {
    id
    name
  }
}
"""


def _attribute_variables(list_of_attributes: list[str]) -> dict[str, Any]:
    variables: dict[str, Any] = {"get_primary_ipv4": True}
    for attr_key in list_of_attributes:
        var_name = _ATTR_TO_VAR.get(attr_key)
        if var_name:
            variables[var_name] = True
    return variables


async def _resolve_device_id_by_name(
    *,
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
    device_name: str,
) -> str | None:
    response = await nautobot_service.graphql_query(
        _DEVICE_BY_NAME_QUERY,
        {"name": [device_name]},
        credentials,
    )
    devices = (response.get("data") or {}).get("devices") or []
    if not devices:
        return None
    device_id = devices[0].get("id")
    return str(device_id) if device_id else None


def _load_nautobot_credentials(
    db: Session,
    source_id: str,
) -> tuple[NautobotCredentials, str]:
    setting_key = build_source_key("nautobot", source_id)
    setting = SettingsRepository(db).get_by_key(setting_key)
    if setting is None:
        raise ValueError(f"Nautobot source '{source_id}' not found in settings")
    nautobot_url = (setting.value or {}).get("url", "").strip()
    nautobot_token = (setting.value or {}).get("token", "").strip()
    if not nautobot_url or not nautobot_token:
        raise ValueError(f"Nautobot source '{source_id}' is missing url or token")
    return service_factory.credentials_from_connection(nautobot_url, nautobot_token), nautobot_url


async def build_sample_context_from_nautobot(
    *,
    db: Session,
    nautobot_source_id: str,
    device_name: str,
    list_of_attributes: list[str],
) -> dict[str, Any]:
    """Fetch one Nautobot device and return a Jinja namespace context."""
    credentials, _ = _load_nautobot_credentials(db, nautobot_source_id)
    nautobot_service = service_factory.get_nautobot_app_service()
    device_name = device_name.strip()
    if not device_name:
        raise ValueError("device_name is required")

    nautobot_device_id = await _resolve_device_id_by_name(
        nautobot_service=nautobot_service,
        credentials=credentials,
        device_name=device_name,
    )
    if nautobot_device_id is None:
        raise ValueError(f"No Nautobot device found with name {device_name!r}")

    detail = await _fetch_device(
        nautobot_service,
        credentials,
        nautobot_device_id,
        _attribute_variables(list_of_attributes),
    )
    if detail is None:
        raise ValueError(f"No Nautobot attribute data returned for {device_name!r}")

    platform_raw = detail.get("platform")
    platform = platform_raw if isinstance(platform_raw, dict) else {}
    primary_ip4 = None
    primary_ip = detail.get("primary_ip4")
    if isinstance(primary_ip, dict):
        primary_ip4 = primary_ip.get("address")

    device = DeviceContext(
        id=str(detail.get("id") or nautobot_device_id),
        name=str(detail.get("name") or device_name),
        hostname=str(detail.get("hostname") or detail.get("name") or device_name),
        platform=platform.get("name"),
        network_driver=platform.get("network_driver"),
        primary_ip4=primary_ip4,
        source="nautobot",
        source_id=nautobot_source_id,
        attribute_bags={"nautobot": _attributes_from_detail(detail)},
        capabilities={Capability.IDENTITY, Capability.ATTRIBUTES},
        status=DeviceStatus.OK,
    )
    return build_jinja_context(
        device,
        run_id="preview-run",
        workflow_id="preview-workflow",
    )


def build_sample_context_from_device_payload(device_payload: dict[str, Any]) -> dict[str, Any]:
    """Build a Jinja namespace context from a workflow DeviceContext payload."""
    device = DeviceContext.model_validate(device_payload)
    return build_jinja_context(
        device,
        run_id="preview-run",
        workflow_id="preview-workflow",
    )

"""Executor for the get-ise-devices step."""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.orm import Session, object_session

import service_factory
from core.models.runs import WorkflowRun
from models.sources_nautobot import DeviceInfo, LogicalCondition, LogicalOperation
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from repositories.settings_repository import SettingsRepository
from services.artifacts import ArtifactService
from services.ise.common.exceptions import ISEAPIError, ISENotFoundError, ISEValidationError
from services.ise.network_device_service import ISENetworkDeviceService
from services.ise.source_config_service import ISESourceNotFoundError
from services.settings.source_keys import build_source_key
from services.sources.nautobot.source_service import NautobotSourceService
from workflow_steps.common.device_builders import (
    device_context_from_ise,
    device_context_from_nautobot,
)

logger = logging.getLogger(__name__)

_QUERY_MODES = {"name", "cidr", "group"}
_LIST_PAGE_SIZE = 100

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


async def _paginate_summaries(
    fetch_page: Callable[[int], Awaitable[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Collect every ``resources`` entry from a paginated ISE SearchResult."""
    summaries: list[dict[str, Any]] = []
    page = 1
    while True:
        result = await fetch_page(page)
        search_result = result.get("SearchResult", {})
        summaries.extend(search_result.get("resources", []))
        if not search_result.get("nextPage"):
            break
        page += 1
    return summaries


async def _fetch_details(
    device_service: ISENetworkDeviceService, summaries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Resolve list summaries (id/name only) into full device detail dicts.

    ISE's list endpoints only return id/name/description — NetworkDeviceIPList
    (the IP address we need) is only present on the per-device detail fetch.
    """
    details: list[dict[str, Any]] = []
    for summary in summaries:
        device_id = summary.get("id")
        if not device_id:
            continue
        try:
            result = await device_service.get_device(device_id)
        except ISENotFoundError:
            logger.warning(
                "get-ise-devices: device id '%s' disappeared before detail fetch, skipping",
                device_id,
            )
            continue
        detail = result.get("NetworkDevice")
        if detail:
            details.append(detail)
    return details


def _ip_in_network(detail: dict[str, Any], network: IPNetwork) -> bool:
    for entry in detail.get("NetworkDeviceIPList") or []:
        raw_ip = entry.get("ipaddress")
        if not raw_ip:
            continue
        try:
            if ipaddress.ip_address(raw_ip) in network:
                return True
        except ValueError:
            continue
    return False


async def _fetch_by_name(
    device_service: ISENetworkDeviceService, names: list[str]
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for raw_name in names:
        name = raw_name.strip()
        if not name:
            continue
        try:
            result = await device_service.get_device_by_name(name)
        except ISENotFoundError:
            logger.warning("get-ise-devices: device name '%s' not found in ISE, skipping", name)
            continue
        detail = result.get("NetworkDevice")
        if detail:
            details.append(detail)
    return details


async def _fetch_by_group(
    device_service: ISENetworkDeviceService, group_name: str
) -> list[dict[str, Any]]:
    summaries = await _paginate_summaries(
        lambda page: device_service.list_devices_by_group(
            group_name, page=page, size=_LIST_PAGE_SIZE
        )
    )
    return await _fetch_details(device_service, summaries)


async def _fetch_by_cidr(
    device_service: ISENetworkDeviceService, cidr: str
) -> list[dict[str, Any]]:
    network = ipaddress.ip_network(cidr, strict=False)

    if network.prefixlen == network.max_prefixlen:
        host = str(network.network_address)
        result = await device_service.list_devices(filter_=f"ipaddress.EQ.{host}")
        summaries = result.get("SearchResult", {}).get("resources", [])
        return await _fetch_details(device_service, summaries)

    # ISE's ERS filter only supports exact-IP matching, not CIDR ranges — scan
    # the full device inventory and filter client-side. Reuses the existing
    # list/get endpoints rather than adding a new ISE-side filter.
    summaries = await _paginate_summaries(
        lambda page: device_service.list_devices(page=page, size=_LIST_PAGE_SIZE)
    )
    details = await _fetch_details(device_service, summaries)
    return [detail for detail in details if _ip_in_network(detail, network)]


async def _fetch_devices(
    device_service: ISENetworkDeviceService, config: dict[str, Any]
) -> list[dict[str, Any]]:
    query_mode = config.get("query_mode", "name")

    if query_mode == "name":
        names = config.get("device_names") or []
        if not names:
            raise ValueError("get-ise-devices: device_names is required for query_mode 'name'")
        return await _fetch_by_name(device_service, names)

    if query_mode == "group":
        group_name = (config.get("group_name") or "").strip()
        if not group_name:
            raise ValueError("get-ise-devices: group_name is required for query_mode 'group'")
        return await _fetch_by_group(device_service, group_name)

    if query_mode == "cidr":
        cidr = (config.get("cidr") or "").strip()
        if not cidr:
            raise ValueError("get-ise-devices: cidr is required for query_mode 'cidr'")
        try:
            return await _fetch_by_cidr(device_service, cidr)
        except ValueError as exc:
            raise ValueError(f"get-ise-devices: invalid cidr '{cidr}': {exc}") from exc

    raise ValueError(f"get-ise-devices: unsupported query_mode '{query_mode}'")


def _cidr_for_group_or_prefix(device: dict[str, Any]) -> str | None:
    """Canonical CIDR (network address/prefix) for an ISE entry's first IP/mask."""
    ip_list = device.get("NetworkDeviceIPList") or []
    if not ip_list:
        return None
    ip = ip_list[0].get("ipaddress")
    mask = ip_list[0].get("mask")
    if not ip or mask is None:
        return None
    try:
        return str(ipaddress.ip_network(f"{ip}/{mask}", strict=False))
    except ValueError:
        return None


def _build_nautobot_source_service(db: Session, nautobot_source_id: str) -> NautobotSourceService:
    setting = SettingsRepository(db).get_by_key(build_source_key("nautobot", nautobot_source_id))
    if setting is None:
        raise ValueError(
            f"get-ise-devices: Nautobot source '{nautobot_source_id}' not found in settings"
        )
    nautobot_url = (setting.value or {}).get("url", "").strip()
    nautobot_token = (setting.value or {}).get("token", "").strip()
    if not nautobot_url or not nautobot_token:
        raise ValueError(
            f"get-ise-devices: Nautobot source '{nautobot_source_id}' is missing url or token"
        )
    credentials = service_factory.credentials_from_connection(nautobot_url, nautobot_token)
    return service_factory.build_nautobot_source_service(credentials, db)


async def _resolve_devices_via_nautobot(
    nautobot_source_service: NautobotSourceService, cidr: str
) -> list[DeviceInfo]:
    """Resolve a subnet/group entry into its member devices via Nautobot's
    "Primary Prefix" filter — devices whose primary_ip4 falls within `cidr`.
    """
    condition = LogicalCondition(field="primary_prefix", operator="within_include", value=cidr)
    operation = LogicalOperation(operation_type="AND", conditions=[condition])
    devices, _ = await nautobot_source_service.preview_inventory([operation])
    return devices


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
        raise ValueError("get-ise-devices: ise_source_id is not configured")

    query_mode = config.get("query_mode", "name")
    if query_mode not in _QUERY_MODES:
        raise ValueError(f"get-ise-devices: unsupported query_mode '{query_mode}'")

    resolve_to_devices = bool(config.get("resolve_to_devices", False))
    nautobot_source_id = (config.get("nautobot_source_id") or "").strip()
    if resolve_to_devices and not nautobot_source_id:
        raise ValueError(
            "get-ise-devices: nautobot_source_id is required when resolve_to_devices is enabled"
        )

    db = object_session(run)
    if db is None:
        raise RuntimeError("get-ise-devices: WorkflowRun has no active DB session")

    source_config_service = service_factory.build_ise_source_config_service(db)
    try:
        credentials = source_config_service.resolve_credentials(source_id)
    except ISESourceNotFoundError as exc:
        raise ValueError(f"get-ise-devices: ISE source '{source_id}' not found") from exc
    except ISEValidationError as exc:
        raise ValueError(f"get-ise-devices: {exc}") from exc

    device_service = service_factory.build_ise_network_device_service(credentials)

    nautobot_source_service: NautobotSourceService | None = None
    if resolve_to_devices:
        nautobot_source_service = _build_nautobot_source_service(db, nautobot_source_id)

    logger.info(
        "get-ise-devices started run_id=%s node_id=%s query_mode=%s resolve_to_devices=%s",
        context.run_id,
        node_id,
        query_mode,
        resolve_to_devices,
    )

    try:
        raw_devices = await _fetch_devices(device_service, config)
    except (ISEValidationError, ISEAPIError) as exc:
        raise RuntimeError(f"get-ise-devices: ISE request failed: {exc}") from exc

    new_devices: dict[str, DeviceContext] = {}
    cidr_cache: dict[str, list[DeviceInfo]] = {}

    for raw_device in raw_devices:
        device_context = device_context_from_ise(raw_device, source_id=source_id)
        is_group_or_prefix = bool(
            device_context.attribute_bags.get("ise", {}).get("is_group_or_prefix")
        )

        if resolve_to_devices and is_group_or_prefix and nautobot_source_service is not None:
            cidr = _cidr_for_group_or_prefix(raw_device)
            resolved_devices: list[DeviceInfo] = []
            if cidr is not None:
                if cidr not in cidr_cache:
                    cidr_cache[cidr] = await _resolve_devices_via_nautobot(
                        nautobot_source_service, cidr
                    )
                resolved_devices = cidr_cache[cidr]

            if resolved_devices:
                for nautobot_device in resolved_devices:
                    resolved_context = device_context_from_nautobot(
                        nautobot_device, source_id=nautobot_source_id
                    )
                    new_devices[resolved_context.id] = resolved_context
                continue

            logger.warning(
                "get-ise-devices: resolve_to_devices found no Nautobot devices for '%s' "
                "(cidr=%s); keeping the raw ISE entry",
                raw_device.get("name"),
                cidr,
            )

        new_devices[device_context.id] = device_context

    fan_out_cfg: dict = config.get("fan_out") or {}
    fan_out_enabled = bool(fan_out_cfg.get("enabled", False))

    metadata_update: dict = {
        **context.metadata,
        f"{node_id}.source_id": source_id,
        f"{node_id}.total": len(new_devices),
    }
    if fan_out_enabled:
        metadata_update["_fan_out"] = {
            "enabled": True,
            "mode": fan_out_cfg.get("mode", "per_device"),
            "chunk_size": max(1, int(fan_out_cfg.get("chunk_size", 1))),
            "max_concurrency": max(0, int(fan_out_cfg.get("max_concurrency", 0))),
            "inventory_node_id": node_id,
        }

    new_context = context.model_copy(
        update={
            "devices": {**context.devices, **new_devices},
            "metadata": metadata_update,
        }
    )

    logger.info(
        "get-ise-devices finished count=%d run_id=%s",
        len(new_devices),
        context.run_id,
    )

    return [
        StepOutcome(
            name="success",
            context=new_context,
            summary=f"found {len(new_devices)} device(s)",
        )
    ]

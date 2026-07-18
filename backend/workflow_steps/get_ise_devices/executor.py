"""Executor for the get-ise-devices step."""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.ise.common.exceptions import ISEAPIError, ISENotFoundError, ISEValidationError
from services.ise.network_device_service import ISENetworkDeviceService
from services.ise.source_config_service import ISESourceNotFoundError
from workflow_steps.common.device_builders import device_context_from_ise

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


def _resolve_group_or_prefix_via_nautobot(device: dict[str, Any]) -> dict[str, Any]:
    """Placeholder for future Nautobot-based expansion of groups/wide prefixes.

    Not yet implemented — currently a no-op that passes the raw ISE entry
    through unchanged. Real expansion (resolving a subnet/group entry into
    its individual member devices via Nautobot) is a follow-up.
    """
    logger.warning(
        "get-ise-devices: resolve_to_devices requested for '%s' but Nautobot-based "
        "expansion is not implemented yet; passing the raw ISE entry through unchanged",
        device.get("name"),
    )
    return device


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

    logger.info(
        "get-ise-devices started run_id=%s node_id=%s query_mode=%s",
        context.run_id,
        node_id,
        query_mode,
    )

    try:
        raw_devices = await _fetch_devices(device_service, config)
    except (ISEValidationError, ISEAPIError) as exc:
        raise RuntimeError(f"get-ise-devices: ISE request failed: {exc}") from exc

    new_devices = {}
    for raw_device in raw_devices:
        device_context = device_context_from_ise(raw_device, source_id=source_id)
        if resolve_to_devices and device_context.attribute_bags.get("ise", {}).get(
            "is_group_or_prefix"
        ):
            _resolve_group_or_prefix_via_nautobot(raw_device)
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

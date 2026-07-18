"""Executor for the get-ise-tacacs-key step.

Fills in ``attribute_bags["tacacs"]["shared_secret"]`` for devices that don't
already have it (e.g. selected via Get from Nautobot / Get from Git), by
looking the key up in Cisco ISE. Devices already carrying the key (e.g.
selected via Get from ISE) are left untouched.

Five lookup tiers, independently enabled and user-ordered:

1. ``name_exact_32``  — device name, only accept a /32 ISE entry.
2. ``name_any``        — device name, accept any netmask.
3. ``location_group``  — Nautobot device location as an ISE Location NDG.
4. ``ip_prefix_scan``  — device's primary IPv4, narrowing /32 down to /8 via
                          ISE's exact-match ``ipaddress.EQ`` filter. Cheap,
                          but only finds entries stored as a clean CIDR
                          network address.
5. ``ip_range_scan``   — full-inventory fallback for ISE entries that use a
                          range (``"192.168.178.1-254"``) or wildcard
                          (``"192.168.178.*"``) notation instead of a clean
                          CIDR address — these can't be found via ISE's
                          server-side filter at all, so this tier fetches
                          every device and checks containment client-side.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

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
from services.ise.common.exceptions import ISEAPIError, ISENotFoundError, ISEValidationError
from services.ise.network_device_service import ISENetworkDeviceService
from services.ise.source_config_service import ISESourceNotFoundError
from workflow_steps.common.attribute_path import resolve_device_value
from workflow_steps.common.attribute_write import set_device_attribute
from workflow_steps.common.ise_lookup import (
    device_ip_list_matches,
    extract_tacacs_shared_secret,
    fetch_ise_device_details,
    paginate_ise_summaries,
)
from workflow_steps.get_ise_tacacs_key.config import get_config

logger = logging.getLogger(__name__)

_STEP_ID = "get-ise-tacacs-key"
_TIER_TYPES = (
    "name_exact_32",
    "name_any",
    "location_group",
    "ip_prefix_scan",
    "ip_range_scan",
)
_LIST_PAGE_SIZE = 100
_MIN_PREFIX_LEN = 8


class _NameLookupCache:
    """Fetches ``get_device_by_name`` at most once per device, shared by the
    two name-based tiers when both are enabled."""

    def __init__(self, device_service: ISENetworkDeviceService, name: str) -> None:
        self._device_service = device_service
        self._name = name
        self._fetched = False
        self._detail: dict[str, Any] | None = None

    async def get(self) -> dict[str, Any] | None:
        if not self._fetched:
            self._fetched = True
            try:
                result = await self._device_service.get_device_by_name(self._name)
                self._detail = result.get("NetworkDevice")
            except ISENotFoundError:
                self._detail = None
        return self._detail


def _parse_priority(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw = config.get("priority")
    if raw is None:
        raw = get_config()["priority"]
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{_STEP_ID}: priority must be a non-empty list")

    items: list[dict[str, Any]] = []
    seen_types: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict) or "type" not in entry:
            raise ValueError(f"{_STEP_ID}: each priority entry needs a 'type'")
        tier_type = entry["type"]
        if tier_type not in _TIER_TYPES:
            raise ValueError(f"{_STEP_ID}: unsupported priority type '{tier_type}'")
        if tier_type in seen_types:
            raise ValueError(f"{_STEP_ID}: duplicate priority type '{tier_type}'")
        seen_types.add(tier_type)
        items.append({"type": tier_type, "enabled": bool(entry.get("enabled", True))})

    if seen_types != set(_TIER_TYPES):
        missing = sorted(set(_TIER_TYPES) - seen_types)
        raise ValueError(f"{_STEP_ID}: priority is missing tier(s): {missing}")

    if not any(item["enabled"] for item in items):
        raise ValueError(f"{_STEP_ID}: at least one priority tier must be enabled")

    return items


def _parse_location_group_prefix(config: dict[str, Any]) -> str:
    prefix = config.get("location_group_prefix") or get_config()["location_group_prefix"]
    return str(prefix).strip() or "All Locations"


async def _tier_name_exact32(cache: _NameLookupCache) -> str | None:
    detail = await cache.get()
    if detail is None:
        return None
    ip_list = detail.get("NetworkDeviceIPList") or []
    if not ip_list or ip_list[0].get("mask") != 32:
        return None
    return extract_tacacs_shared_secret(detail)


async def _tier_name_any(cache: _NameLookupCache) -> str | None:
    detail = await cache.get()
    if detail is None:
        return None
    return extract_tacacs_shared_secret(detail)


async def _tier_location_group(
    device: DeviceContext,
    device_service: ISENetworkDeviceService,
    group_prefix: str,
) -> str | None:
    location_name = (device.attribute_bags.get("nautobot", {}).get("location") or {}).get("name")
    if not location_name:
        return None

    full_group_name = f"Location#{group_prefix}#{location_name}"
    summaries = await paginate_ise_summaries(
        lambda page: device_service.list_devices_by_group(
            full_group_name, page=page, size=_LIST_PAGE_SIZE
        )
    )
    if not summaries:
        return None

    details = await fetch_ise_device_details(device_service, summaries)
    for detail in details:
        secret = extract_tacacs_shared_secret(detail)
        if secret:
            return secret
    return None


def _effective_primary_ip4(device: DeviceContext) -> str | None:
    """Prefer the top-level field (set by Get from Nautobot/Get from Git); fall
    back to the ``nautobot`` attribute bag, which is the only place the IP
    lives when a device came from Get from List/Get from ISE and was later
    enriched by a Get Nautobot Attributes step."""
    if device.primary_ip4:
        return device.primary_ip4
    value = resolve_device_value(device, "nautobot.primary_ip4.address")
    return str(value) if value else None


async def _tier_ip_prefix_scan(
    device: DeviceContext, device_service: ISENetworkDeviceService
) -> str | None:
    bare_ip = (_effective_primary_ip4(device) or "").split("/")[0].strip()
    if not bare_ip:
        return None
    try:
        ipaddress.ip_address(bare_ip)
    except ValueError:
        return None

    for prefixlen in range(32, _MIN_PREFIX_LEN - 1, -1):
        network = ipaddress.ip_network(f"{bare_ip}/{prefixlen}", strict=False)
        candidate = str(network.network_address)
        result = await device_service.list_devices(filter_=f"ipaddress.EQ.{candidate}")
        resources = result.get("SearchResult", {}).get("resources", [])
        if not resources:
            continue
        details = await fetch_ise_device_details(device_service, resources)
        for detail in details:
            secret = extract_tacacs_shared_secret(detail)
            if secret:
                return secret
    return None


async def _tier_ip_range_scan(
    device: DeviceContext, device_service: ISENetworkDeviceService
) -> str | None:
    raw_ip = (_effective_primary_ip4(device) or "").split("/")[0].strip()
    if not raw_ip:
        return None
    try:
        target = ipaddress.IPv4Address(raw_ip)
    except ValueError:
        return None

    summaries = await paginate_ise_summaries(
        lambda page: device_service.list_devices(page=page, size=_LIST_PAGE_SIZE)
    )
    details = await fetch_ise_device_details(device_service, summaries)
    for detail in details:
        if not device_ip_list_matches(detail, target):
            continue
        secret = extract_tacacs_shared_secret(detail)
        if secret:
            return secret
    return None


async def _find_tacacs_key(
    *,
    device: DeviceContext,
    device_service: ISENetworkDeviceService,
    priority: list[dict[str, Any]],
    location_group_prefix: str,
) -> tuple[str | None, str | None]:
    """Try each enabled tier in configured order; return (secret, matched_tier)."""
    name_cache = _NameLookupCache(device_service, device.name)

    for item in priority:
        if not item["enabled"]:
            continue
        tier_type = item["type"]
        try:
            if tier_type == "name_exact_32":
                secret = await _tier_name_exact32(name_cache)
            elif tier_type == "name_any":
                secret = await _tier_name_any(name_cache)
            elif tier_type == "location_group":
                secret = await _tier_location_group(device, device_service, location_group_prefix)
            elif tier_type == "ip_prefix_scan":
                secret = await _tier_ip_prefix_scan(device, device_service)
            else:
                secret = await _tier_ip_range_scan(device, device_service)
        except (ISEValidationError, ISEAPIError) as exc:
            logger.warning(
                "%s: tier=%s failed for device=%s: %s", _STEP_ID, tier_type, device.name, exc
            )
            continue

        if secret:
            return secret, tier_type

    return None, None


def _mark_not_found(device: DeviceContext, *, node_id: str, source_id: str) -> DeviceContext:
    error = DeviceError(
        node_id=node_id,
        step_id=_STEP_ID,
        code="tacacs_key_not_found",
        message=(
            f"No enabled priority tier found a TACACS+ key for '{device.name}' "
            f"in ISE source '{source_id}'"
        ),
    )
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, error]}
    )


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

    priority = _parse_priority(config)
    location_group_prefix = _parse_location_group_prefix(config)

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

    updated_devices: dict[str, DeviceContext] = {}
    found_count = 0
    already_present_count = 0
    not_found_count = 0

    for device_id, device in context.devices.items():
        existing_secret = (device.attribute_bags.get("tacacs") or {}).get("shared_secret")
        if existing_secret:
            updated_devices[device_id] = device
            already_present_count += 1
            continue

        try:
            secret, matched_tier = await _find_tacacs_key(
                device=device,
                device_service=device_service,
                priority=priority,
                location_group_prefix=location_group_prefix,
            )
        except ValueError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"{_STEP_ID}: failed for device '{device.name}': {exc}"
            ) from exc

        if secret:
            updated_devices[device_id] = set_device_attribute(
                device, "tacacs.shared_secret", secret
            )
            found_count += 1
            logger.info(
                "%s: found tacacs key for device=%s tier=%s", _STEP_ID, device.name, matched_tier
            )
        else:
            updated_devices[device_id] = _mark_not_found(
                device, node_id=node_id, source_id=source_id
            )
            not_found_count += 1

    metadata = {
        **context.metadata,
        f"{node_id}.total": len(context.devices),
        f"{node_id}.found_count": found_count,
        f"{node_id}.already_present_count": already_present_count,
        f"{node_id}.not_found_count": not_found_count,
    }

    logger.info(
        "%s finished node_id=%s found=%d already_present=%d not_found=%d run_id=%s",
        _STEP_ID,
        node_id,
        found_count,
        already_present_count,
        not_found_count,
        context.run_id,
    )

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": updated_devices, "metadata": metadata}),
            summary=(
                f"found {found_count}, already had key {already_present_count}, "
                f"not found {not_found_count}"
            ),
        )
    ]

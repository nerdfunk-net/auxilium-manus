"""Executor for the get-ise-tacacs-key step.

Fills in ``attribute_bags["tacacs"]["shared_secret"]`` for devices that don't
already have it (e.g. selected via Get from Nautobot / Get from Git), by
looking the key up in Cisco ISE. Devices already carrying the key (e.g.
selected via Get from ISE) are left untouched.

On a hit, the tier that found the key is written next to it as
``attribute_bags["tacacs"]["key_strategy"]`` (one of the tier ids below).

Outcomes (DN-A): only devices that carry a key (found now, or already present) leave through
``"success"``. A per-device miss (no enabled tier found a key) marks that device
``DeviceStatus.FAILED`` and routes it through ``"failure"`` — the idiom this unlocks is
``Get TACACS+ Key from ISE -> failure -> Add to ISE``. When ISE is lost mid-run the devices
already processed keep their result and every unprocessed device leaves through
``"failure"`` with the transport cause. A failed pre-flight ``test_connection()`` check
emits ``"failure"`` for all devices.

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

import asyncio
import ipaddress
import logging
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.ise.common.exceptions import ISEAPIError, ISENotFoundError, ISEValidationError
from services.ise.lookup import (
    device_ip_list_matches,
    extract_tacacs_shared_secret,
    fetch_ise_device_details,
    paginate_ise_summaries,
)
from services.ise.network_device_service import ISENetworkDeviceService
from services.workflow_context.secret_fields import seal_secret, secret_is_present
from workflow_steps.common.attribute_write import set_device_attribute
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.device_runner import AbortRun, Fail, run_per_device
from workflow_steps.common.ise_step import build_ise_device_service, preflight_ise
from workflow_steps.common.partial_outcomes import abort_outcomes
from workflow_steps.common.primary_ip import effective_primary_ip4
from workflow_steps.common.step_flags import parse_bool_flag
from workflow_steps.get_ise_tacacs_key.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "get-ise-tacacs-key"
_TIER_TYPES: tuple[str, ...] = (
    "name_exact_32",
    "name_any",
    "location_group",
    "ip_prefix_scan",
    "ip_range_scan",
)
_KEY_STRATEGY_PATH = "tacacs.key_strategy"
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
        enabled = parse_bool_flag(entry, "enabled", default=True, step_id=_STEP_ID)
        items.append({"type": tier_type, "enabled": enabled})

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


class _LocationGroups:
    """The detail records of each ``Location#...`` group, listed once per step run: the group
    depends only on the location, so devices of one location share it (W6-07). A failed
    listing is not remembered, the next device asks again."""

    def __init__(self, device_service: ISENetworkDeviceService) -> None:
        self._service = device_service
        self._details: dict[str, list[dict[str, Any]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def details(self, group_name: str) -> list[dict[str, Any]]:
        lock = self._locks.setdefault(group_name, asyncio.Lock())
        async with lock:
            if group_name not in self._details:
                summaries = await paginate_ise_summaries(
                    lambda page: self._service.list_devices_by_group(
                        group_name, page=page, size=_LIST_PAGE_SIZE
                    )
                )
                self._details[group_name] = (
                    await fetch_ise_device_details(self._service, summaries) if summaries else []
                )
            return self._details[group_name]


async def _tier_location_group(
    device: DeviceContext,
    device_service: ISENetworkDeviceService,
    group_prefix: str,
    groups: _LocationGroups | None = None,
) -> str | None:
    location_name = (device.attribute_bags.get("nautobot", {}).get("location") or {}).get("name")
    if not location_name:
        return None

    full_group_name = f"Location#{group_prefix}#{location_name}"
    groups = groups or _LocationGroups(device_service)
    for detail in await groups.details(full_group_name):
        secret = extract_tacacs_shared_secret(detail)
        if secret:
            return secret
    return None


class _IseInventory:
    """All ISE network devices (detail records), fetched once per step run and shared by every
    device: the range scan used to download the whole inventory per device (C3R-03)."""

    def __init__(self, device_service: ISENetworkDeviceService) -> None:
        self._service = device_service
        self._details: list[dict[str, Any]] | None = None
        self._lock = asyncio.Lock()

    async def details(self) -> list[dict[str, Any]]:
        async with self._lock:
            if self._details is None:
                summaries = await paginate_ise_summaries(
                    lambda page: self._service.list_devices(page=page, size=_LIST_PAGE_SIZE)
                )
                self._details = await fetch_ise_device_details(
                    self._service, summaries, concurrency=8
                )
            return self._details


async def _tier_ip_prefix_scan(
    device: DeviceContext, device_service: ISENetworkDeviceService
) -> str | None:
    bare_ip = (effective_primary_ip4(device) or "").split("/")[0].strip()
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
            # Accept a key only from an entry that really contains the device (C3R-02).
            if not device_ip_list_matches(detail, ipaddress.IPv4Address(bare_ip)):
                continue
            secret = extract_tacacs_shared_secret(detail)
            if secret:
                return secret
    return None


async def _tier_ip_range_scan(device: DeviceContext, inventory: _IseInventory) -> str | None:
    raw_ip = (effective_primary_ip4(device) or "").split("/")[0].strip()
    if not raw_ip:
        return None
    try:
        target = ipaddress.IPv4Address(raw_ip)
    except ValueError:
        return None

    for detail in await inventory.details():
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
    inventory: _IseInventory | None = None,
    location_groups: _LocationGroups | None = None,
) -> tuple[str | None, str | None]:
    """Try each enabled tier in configured order; return (secret, matched_tier)."""
    inventory = inventory or _IseInventory(device_service)
    location_groups = location_groups or _LocationGroups(device_service)
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
                secret = await _tier_location_group(
                    device, device_service, location_group_prefix, location_groups
                )
            elif tier_type == "ip_prefix_scan":
                secret = await _tier_ip_prefix_scan(device, device_service)
            else:
                secret = await _tier_ip_range_scan(device, inventory)
        except (ISENotFoundError, ISEValidationError) as exc:
            # Not found / bad request for this specific tier's query — a tier
            # miss, not a reason to stop. A bare ISEAPIError (unreachable ISE,
            # timeout, auth failure) is NOT caught here — it propagates so the
            # caller can route the whole step to the "failure" outcome instead
            # of silently treating every device as "key not found".
            logger.warning(
                "%s: tier=%s found nothing for device=%s: %s", _STEP_ID, tier_type, device.name, exc
            )
            continue

        if secret:
            return secret, tier_type

    return None, None


async def _process_devices_for_tacacs_key(
    *,
    context: WorkflowContext,
    device_service: ISENetworkDeviceService,
    priority: list[dict[str, Any]],
    location_group_prefix: str,
    node_id: str,
    source_id: str,
) -> list[StepOutcome]:
    inventory = _IseInventory(device_service)  # one inventory download per step run
    location_groups = _LocationGroups(device_service)  # one listing per location group
    found: set[str] = set()  # key found now (the rest of the successes already had one)

    async def work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        existing_secret = (device.attribute_bags.get("tacacs") or {}).get("shared_secret")
        if secret_is_present(existing_secret):
            return device

        try:
            secret, matched_tier = await _find_tacacs_key(
                device=device,
                device_service=device_service,
                priority=priority,
                location_group_prefix=location_group_prefix,
                inventory=inventory,
                location_groups=location_groups,
            )
        except ISEAPIError as exc:
            logger.warning(
                "%s: lost connection to ISE source '%s' while processing device '%s': %s",
                _STEP_ID,
                source_id,
                device.name,
                exc,
            )
            raise AbortRun(f"lost connection to ISE source '{source_id}'", exc.failure) from exc

        if not secret:
            return Fail(
                code="tacacs_key_not_found",
                message=(
                    f"No enabled priority tier found a TACACS+ key for '{device.name}' "
                    f"in ISE source '{source_id}'"
                ),
                failure=FailureInfo(phase="api", kind="not_found"),
            )
        with_secret = set_device_attribute(device, "tacacs.shared_secret", seal_secret(secret))
        # Record which lookup tier succeeded (one of _TIER_TYPES) so downstream steps and run
        # output can tell how the key was found.
        found.add(device_id)
        logger.info(
            "%s: found tacacs key for device=%s tier=%s", _STEP_ID, device.name, matched_tier
        )
        return set_device_attribute(with_secret, _KEY_STRATEGY_PATH, matched_tier)

    # One device after the other (the inventory and location caches are shared): a lost ISE
    # connection stops the run and the devices already done keep their result (DN-A).
    batch = await run_per_device(
        context, work, node_id=node_id, step_id=_STEP_ID, concurrency=1
    )
    if batch.aborted is not None:
        return abort_outcomes(
            context=context,
            node_id=node_id,
            step_id=_STEP_ID,
            done_ok=batch.ok,
            done_failed=batch.failed,
            message=batch.aborted.message,
            failure=batch.aborted.failure,
        )

    found_count = len(found)
    already_present_count = len(batch.ok) - found_count
    not_found_count = len(batch.failed)
    logger.info(
        "%s finished node_id=%s found=%d already_present=%d not_found=%d run_id=%s",
        _STEP_ID,
        node_id,
        found_count,
        already_present_count,
        not_found_count,
        context.run_id,
    )
    return build_outcomes(
        context,
        batch.ok,
        batch.failed,
        metadata={
            f"{node_id}.total": len(context.devices),
            f"{node_id}.found_count": found_count,
            f"{node_id}.already_present_count": already_present_count,
            f"{node_id}.not_found_count": not_found_count,
        },
        success_summary=(
            f"found {found_count}, already had key {already_present_count}, "
            f"not found {not_found_count}"
        ),
        failure_summary=f"no key found for {not_found_count} device(s)",
    )


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

    source_id = (config.get("ise_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: ise_source_id is not configured")

    priority = _parse_priority(config)
    location_group_prefix = _parse_location_group_prefix(config)

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    device_service = build_ise_device_service(run, source_id, step_id=_STEP_ID)

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d",
        _STEP_ID,
        context.run_id,
        node_id,
        len(context.devices),
    )

    unreachable = await preflight_ise(device_service, context, source_id, step_id=_STEP_ID)
    if unreachable is not None:
        return unreachable

    return await _process_devices_for_tacacs_key(
        context=context,
        device_service=device_service,
        priority=priority,
        location_group_prefix=location_group_prefix,
        node_id=node_id,
        source_id=source_id,
    )

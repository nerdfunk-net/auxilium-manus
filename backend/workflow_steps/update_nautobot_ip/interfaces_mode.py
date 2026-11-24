"""The "IP addresses from interfaces" mode of update-nautobot-ip.

Reads every IP address on the interfaces of each device (the ``nautobot`` attribute bag, Get
Nautobot Attributes with interfaces on) and applies the values the user configured to all of them:
status, type, role and namespace are the same for every address, ``dns_name`` and ``description``
may use per-address tokens (``address_values.py``). The values cannot be derived from the device;
only the *set of addresses* comes from the interfaces.

- An address that is also assigned to something outside the device (HSRP / VRRP / anycast, another
  device's or a VM interface) is skipped and reported: changing it would change it for every holder.
  It is also why an address handled here belongs to one device only, so de-duplicating by address id
  per device is enough.
- An address is handled once per device however many interfaces list it.
- ``dry_run`` writes nothing: each address is read and the preview names the fields that would
  change (``dry_run_results``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from models.workflow_context import DeviceContext, DeviceError, StepOutcome, WorkflowContext
from services.nautobot.common.validators import is_valid_uuid
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.devices.common import DeviceCommonService
from workflow_steps.common.nautobot_plan_fields import bad_request_failure, resolve_fields
from workflow_steps.common.partial_outcomes import (
    device_error_from_exception,
    fail_device_with_error,
)
from workflow_steps.common.step_flags import record_dry_run
from workflow_steps.update_nautobot_ip.address_values import AddressRef, render_address_value
from workflow_steps.update_nautobot_ip.lookups import (
    STEP_ID,
    Plan,
    failed,
    lookup_error,
    parent_finder,
    resolve_ids,
    split_values,
    write_error,
)

logger = logging.getLogger(__name__)

_CONCURRENCY = 5
_OUTCOME_NAMES = ("success", "failure")
_DEVICE_FIELDS = ("namespace", "type", "role", "status")  # the same for every address
_ADDRESS_FIELDS = ("dns_name", "description")  # may differ per address


@dataclass(frozen=True)
class _Item:
    ref: AddressRef
    fields: dict[str, str]


@dataclass(frozen=True)
class _Prepared:
    device: DeviceContext
    items: list[_Item]
    skipped_shared: list[AddressRef]
    namespace_id: str | None
    # Addresses for which every value rendered empty (e.g. {interface.slug} of "///").
    skipped_empty: list[AddressRef] = field(default_factory=list)


@dataclass(frozen=True)
class _Result:
    changed: bool
    fields: list[str]
    error: DeviceError | None = None


def _addresses(bag: dict[str, Any], ip_version: str) -> list[AddressRef]:
    """Every distinct address on the bag's interfaces (the first interface that lists it wins)."""
    found: dict[str, AddressRef] = {}
    for interface in bag.get("interfaces") or []:
        if not isinstance(interface, dict):
            continue
        for raw in interface.get("ip_addresses") or []:
            if not isinstance(raw, dict):
                continue
            ip_id = str(raw.get("id") or "").lower()
            address = str(raw.get("address") or "")
            if not is_valid_uuid(ip_id) or not address:
                continue
            if ip_version and str(raw.get("ip_version")) != ip_version:
                continue
            found.setdefault(
                ip_id,
                AddressRef(
                    id=ip_id,
                    address=address,
                    interface_name=str(interface.get("name") or ""),
                    interface_id=str(interface.get("id") or ""),
                ),
            )
    return list(found.values())


def _own_interface_ids(bag: dict[str, Any]) -> set[str]:
    return {
        str(interface["id"]).lower()
        for interface in bag.get("interfaces") or []
        if isinstance(interface, dict) and interface.get("id")
    }


async def _prepare(
    *,
    common: DeviceCommonService,
    device: DeviceContext,
    run_id: str,
    node_id: str,
    expressions: dict[str, str],
    ip_version: str,
    cache: dict[tuple[str, str], str | Exception],
) -> _Prepared | DeviceContext:
    """The addresses to update for a device, or the failed device."""
    bag = device.attribute_bags.get("nautobot")
    if not isinstance(bag, dict) or not isinstance(bag.get("interfaces"), list):
        return failed(
            device,
            node_id=node_id,
            code="interfaces_missing",
            message=(
                "The device has no interfaces in its Nautobot attributes; "
                "switch interfaces on in Get Nautobot Attributes"
            ),
            failure=bad_request_failure(),
        )
    refs = _addresses(bag, ip_version)
    if not refs:
        return _Prepared(device, [], [], None)

    resolved = resolve_fields(
        device, run_id, tuple((field, expressions.get(field, "")) for field in _DEVICE_FIELDS)
    )
    if isinstance(resolved, tuple):
        code, message, failure = resolved
        return failed(device, node_id=node_id, code=code, message=message, failure=failure)
    split = split_values(resolved, allow_empty=True)
    if isinstance(split, tuple):
        code, message, failure = split
        return failed(device, node_id=node_id, code=code, message=message, failure=failure)
    base = await resolve_ids(common, Plan(device, "", split.values, split.namespace), cache)
    if isinstance(base, tuple):
        code, exc = base
        return lookup_error(code, exc, node_id, device)

    try:
        shared = await common.shared_ip_ids([ref.id for ref in refs], _own_interface_ids(bag))
    except Exception as exc:
        error = device_error_from_exception(exc, node_id=node_id, step_id=STEP_ID)
        return fail_device_with_error(device, error)

    items: list[_Item] = []
    skipped_empty: list[AddressRef] = []
    for ref in refs:
        if ref.id in shared:
            continue
        fields = dict(base.values)
        for field_name in _ADDRESS_FIELDS:
            raw = expressions.get(field_name, "")
            if not raw:
                continue
            value = render_address_value(raw, device, ref, field=field_name, run_id=run_id)
            if isinstance(value, tuple):
                code, message, failure = value
                return failed(device, node_id=node_id, code=code, message=message, failure=failure)
            if value:
                fields[field_name] = value
        if not fields and base.namespace is None:
            # This one address renders to nothing (a per-address value of an odd interface name):
            # skip it and say so. The others are fine, and the empty-configuration code
            # (``nothing_to_update``) means the step's own configuration is empty.
            skipped_empty.append(ref)
            continue
        items.append(_Item(ref, fields))
    skipped = [ref for ref in refs if ref.id in shared]
    return _Prepared(device, items, skipped, base.namespace, skipped_empty)


def _field_names(changes: dict[str, str]) -> list[str]:
    """The config field names of a change set (a ``parent`` change is the namespace move)."""
    return sorted("namespace" if key == "parent" else key for key in changes)


async def _handle(
    common: DeviceCommonService,
    find_parent: Callable[[str], Awaitable[str]] | None,
    item: _Item,
    *,
    node_id: str,
    dry_run: bool,
) -> _Result:
    try:
        if dry_run:
            changes = await common.plan_ip_update(item.ref.id, item.fields, find_parent=find_parent)
            return _Result(bool(changes), _field_names(changes))
        changed = await common.update_ip_address(item.ref.id, item.fields, find_parent=find_parent)
        return _Result(changed, [])
    except Exception as exc:
        logger.warning("%s: update failed ip_id=%s", STEP_ID, item.ref.id)
        return _Result(False, [], write_error(exc, node_id))


def _finish(
    prepared: _Prepared, results: list[_Result], *, node_id: str, dry_run: bool
) -> tuple[str, DeviceContext]:
    errors = [result.error for result in results if result.error is not None]
    if errors:
        first = errors[0]
        message = f"{len(errors)} of {len(results)} addresses could not be updated: {first.message}"
        return "failure", fail_device_with_error(
            prepared.device, first.model_copy(update={"message": message})
        )
    device = prepared.device
    if dry_run:
        changing = [
            {"ip_id": item.ref.id, "address": item.ref.address, "fields": result.fields}
            for item, result in zip(prepared.items, results, strict=True)
            if result.changed
        ]
        device = record_dry_run(
            device,
            node_id=node_id,
            payload={
                "would_change": changing,
                "unchanged": len(results) - len(changing),
                "skipped_shared": [
                    {"ip_id": ref.id, "address": ref.address} for ref in prepared.skipped_shared
                ],
                "skipped_empty": [
                    {"ip_id": ref.id, "address": ref.address} for ref in prepared.skipped_empty
                ],
            },
        )
    return "success", device


async def run_from_interfaces(
    *,
    common: DeviceCommonService,
    client: CredentialsBoundNautobotClient,
    context: WorkflowContext,
    node_id: str,
    expressions: dict[str, str],
    ip_version: str,
    dry_run: bool,
) -> list[StepOutcome]:
    buckets: dict[str, dict[str, DeviceContext]] = {name: {} for name in _OUTCOME_NAMES}
    prepared: list[_Prepared] = []
    cache: dict[tuple[str, str], str | Exception] = {}
    # One device after another so a shared status / role / namespace name is looked up once.
    for device in context.devices.values():
        result = await _prepare(
            common=common,
            device=device,
            run_id=context.run_id,
            node_id=node_id,
            expressions=expressions,
            ip_version=ip_version,
            cache=cache,
        )
        if isinstance(result, DeviceContext):
            buckets["failure"][device.id] = result
        else:
            prepared.append(result)

    gate = asyncio.Semaphore(_CONCURRENCY)

    async def one(entry: _Prepared, item: _Item) -> _Result:
        find_parent = parent_finder(client, entry.namespace_id) if entry.namespace_id else None
        async with gate:
            return await _handle(common, find_parent, item, node_id=node_id, dry_run=dry_run)

    gathered = await asyncio.gather(
        *[one(entry, item) for entry in prepared for item in entry.items]
    )
    results = iter(gathered)
    totals = {"updated": 0, "unchanged": 0, "failed": 0, "skipped_shared": 0, "skipped_empty": 0}
    for entry in prepared:
        mine = [next(results) for _ in entry.items]
        bucket, device = _finish(entry, mine, node_id=node_id, dry_run=dry_run)
        buckets[bucket][entry.device.id] = device
        totals["skipped_shared"] += len(entry.skipped_shared)
        totals["skipped_empty"] += len(entry.skipped_empty)
        for result in mine:
            key = "failed" if result.error else "updated" if result.changed else "unchanged"
            totals[key] += 1

    metadata = {
        **context.metadata,
        f"{node_id}.update_ip_counts": {**totals, "dry_run": dry_run},
    }
    return [
        StepOutcome(
            name=name,
            context=context.model_copy(
                update={"devices": dict(buckets[name]), "metadata": metadata}
            ),
        )
        for name in _OUTCOME_NAMES
    ]

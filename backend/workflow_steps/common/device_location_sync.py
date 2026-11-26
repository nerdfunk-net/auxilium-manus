"""Add each device's location to the objects found in its Nautobot attributes.

The engine behind the "from interfaces" mode of ``update-nautobot-vlan`` and
``update-nautobot-prefix``. A step supplies a :class:`LocationSyncSpec` (how to find the objects
in the device's ``nautobot`` attribute bag and how to write or check one); the engine reads the
device's location id, makes sure each object has that location in its list (``add``, never
removes one) and builds the outcomes.

An (object, location) pair is handled once per execution however many devices or interfaces name
it, so two devices at one site that share an object do not both try to create the same
assignment. Whether an object already has the location is always Nautobot's answer, never the
attribute bag's: the bag is a snapshot, so a location removed after it was read would otherwise
be reported as present (in a dry run too). With ``dry_run`` nothing is written: Nautobot is
read and the preview is stored per device (``dry_run_results``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from models.failure import FailureInfo
from models.workflow_context import DeviceContext, DeviceError, StepOutcome, WorkflowContext
from services.nautobot.common.validators import is_valid_uuid
from workflow_steps.common.device_outcomes import fail_device_with_error
from workflow_steps.common.partial_outcomes import (
    NAUTOBOT_TEXT,
    device_error_from_exception,
)
from workflow_steps.common.step_flags import record_dry_run

logger = logging.getLogger(__name__)

_CONCURRENCY = 5
_OUTCOME_NAMES = ("success", "failure")
_BAG = "nautobot"

Pair = tuple[str, str]
# (object id, location id) -> True when the object lacked the location (written / would be)
PairAction = Callable[[str, str], Awaitable[bool]]


@dataclass(frozen=True)
class SyncRef:
    """One object of a device: its id and a preview entry for the dry run."""

    id: str
    preview: dict[str, Any]


@dataclass(frozen=True)
class LocationSyncSpec:
    step_id: str
    #: Metadata key suffix of the counts (``"<node>.<counts_key>"``), e.g. ``update_vlan_counts``.
    counts_key: str
    #: Plural noun of the objects, for the failure message ("3 of 5 VLANs could not ...").
    noun: str
    #: The bag -> every distinct object of the device's interfaces (first mention wins)
    extract: Callable[[dict[str, Any]], list[SyncRef]]
    #: Add the location to the object; True when something was written.
    write: PairAction
    #: Dry run: would the object get the location (a read)?
    check: PairAction


def uuid_or_none(value: Any) -> str | None:
    if isinstance(value, str) and is_valid_uuid(value.strip().lower()):
        return value.strip().lower()
    return None


def _config_failure(
    device: DeviceContext, spec: LocationSyncSpec, node_id: str, code: str, message: str
) -> DeviceContext:
    error = DeviceError(
        node_id=node_id,
        step_id=spec.step_id,
        code=code,
        message=message,
        failure=FailureInfo(phase="config", kind="bad_request", hint="check_request"),
    )
    return fail_device_with_error(device, error)


@dataclass(frozen=True)
class _Work:
    device: DeviceContext
    location_id: str
    refs: list[SyncRef]


def _plan(device: DeviceContext, spec: LocationSyncSpec, node_id: str) -> _Work | DeviceContext:
    """The work for a device, or the failed device when its bag lacks what the mode needs."""
    bag = device.attribute_bags.get(_BAG)
    if not isinstance(bag, dict):
        bag = {}
    location = bag.get("location")
    location_id = uuid_or_none(location.get("id")) if isinstance(location, dict) else None
    if location_id is None:
        return _config_failure(
            device,
            spec,
            node_id,
            "device_location_missing",
            "The device has no Nautobot location in its attributes; "
            "run Get Nautobot Attributes first",
        )
    if not isinstance(bag.get("interfaces"), list):
        return _config_failure(
            device,
            spec,
            node_id,
            "interfaces_missing",
            "The device has no interfaces in its Nautobot attributes; "
            "switch interfaces on in Get Nautobot Attributes",
        )
    return _Work(device, location_id, spec.extract(bag))


async def _handle_pairs(
    spec: LocationSyncSpec, pairs: set[Pair], *, dry_run: bool
) -> dict[Pair, bool | Exception]:
    gate = asyncio.Semaphore(_CONCURRENCY)
    ordered = sorted(pairs)
    action = spec.check if dry_run else spec.write

    async def one(pair: Pair) -> bool | Exception:
        async with gate:
            try:
                return await action(*pair)
            except Exception as exc:
                logger.warning("%s: location update failed id=%s", spec.step_id, pair[0])
                return exc

    results = await asyncio.gather(*[one(pair) for pair in ordered])
    return dict(zip(ordered, results, strict=True))


def _finish_device(
    work: _Work,
    results: dict[Pair, bool | Exception],
    spec: LocationSyncSpec,
    *,
    node_id: str,
    dry_run: bool,
) -> tuple[str, DeviceContext]:
    changed: list[SyncRef] = []
    unchanged = 0
    first_error: Exception | None = None
    failed = 0
    for ref in work.refs:
        result = results[(ref.id, work.location_id)]
        if isinstance(result, Exception):
            failed += 1
            first_error = first_error or result
        elif result:
            changed.append(ref)
        else:
            unchanged += 1
    if first_error is not None:
        error = device_error_from_exception(
            first_error, node_id=node_id, step_id=spec.step_id, keep_text=NAUTOBOT_TEXT
        )
        message = f"{failed} of {len(work.refs)} {spec.noun} could not be updated: {error.message}"
        return "failure", fail_device_with_error(
            work.device, error.model_copy(update={"message": message})
        )
    device = work.device
    if dry_run:
        device = record_dry_run(
            device,
            node_id=node_id,
            payload={
                "would_add_location": [ref.preview for ref in changed],
                "already_assigned": unchanged,
                "location_id": work.location_id,
            },
        )
    return "success", device


async def run_location_sync(
    spec: LocationSyncSpec,
    *,
    context: WorkflowContext,
    node_id: str,
    dry_run: bool,
) -> list[StepOutcome]:
    buckets: dict[str, dict[str, DeviceContext]] = {name: {} for name in _OUTCOME_NAMES}
    work_items: list[_Work] = []
    for device in context.devices.values():
        planned = _plan(device, spec, node_id)
        if isinstance(planned, DeviceContext):
            buckets["failure"][device.id] = planned
        else:
            work_items.append(planned)

    pairs = {(ref.id, work.location_id) for work in work_items for ref in work.refs}
    results = await _handle_pairs(spec, pairs, dry_run=dry_run) if pairs else {}

    for work in work_items:
        bucket, device = _finish_device(work, results, spec, node_id=node_id, dry_run=dry_run)
        buckets[bucket][work.device.id] = device

    # Totals count (object, location) pairs, so a pair shared by devices is counted once.
    totals = {"updated": 0, "unchanged": 0, "failed": 0}
    for result in results.values():
        key = "failed" if isinstance(result, Exception) else "updated" if result else "unchanged"
        totals[key] += 1
    metadata = {
        **context.metadata,
        f"{node_id}.{spec.counts_key}": {**totals, "dry_run": dry_run},
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

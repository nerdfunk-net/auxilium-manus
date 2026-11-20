"""The "VLANs from interfaces" mode of update-nautobot-vlan.

Reads the tagged and untagged VLAN ids of each device's interfaces (from the ``nautobot`` attribute
bag) and adds the device's location to each VLAN; the shared engine is
``workflow_steps/common/device_location_sync.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from models.workflow_context import StepOutcome, WorkflowContext
from workflow_steps.common.device_location_sync import (
    LocationSyncSpec,
    SyncRef,
    run_location_sync,
    uuid_or_none,
)

if TYPE_CHECKING:
    from services.nautobot.devices.common import DeviceCommonService

_STEP_ID = "update-nautobot-vlan"


def _vlan_ref(raw: Any) -> SyncRef | None:
    if not isinstance(raw, dict):
        return None
    vlan_id = uuid_or_none(raw.get("id"))
    if vlan_id is None:
        return None
    vid = raw.get("vid")
    return SyncRef(
        id=vlan_id,
        preview={
            "vlan_id": vlan_id,
            "vid": vid if isinstance(vid, int) else None,
            "name": str(raw.get("name") or ""),
        },
    )


def _interface_vlans(bag: dict[str, Any]) -> list[SyncRef]:
    """Every distinct tagged and untagged VLAN of the bag's interfaces (first mention wins)."""
    found: dict[str, SyncRef] = {}
    for interface in bag.get("interfaces") or []:
        if not isinstance(interface, dict):
            continue
        tagged = interface.get("tagged_vlans")
        candidates = [interface.get("untagged_vlan"), *(tagged if isinstance(tagged, list) else [])]
        for raw in candidates:
            ref = _vlan_ref(raw)
            if ref is not None:
                found.setdefault(ref.id, ref)
    return list(found.values())


async def run_from_interfaces(
    *,
    common: DeviceCommonService,
    context: WorkflowContext,
    node_id: str,
    dry_run: bool,
) -> list[StepOutcome]:
    async def write(vlan_id: str, location_id: str) -> bool:
        return await common.update_vlan(vlan_id, {}, locations=[location_id], locations_mode="add")

    async def check(vlan_id: str, location_id: str) -> bool:
        return bool(await common.missing_vlan_locations(vlan_id, [location_id]))

    spec = LocationSyncSpec(
        step_id=_STEP_ID,
        counts_key="update_vlan_counts",
        noun="VLANs",
        extract=_interface_vlans,
        write=write,
        check=check,
    )
    return await run_location_sync(spec, context=context, node_id=node_id, dry_run=dry_run)

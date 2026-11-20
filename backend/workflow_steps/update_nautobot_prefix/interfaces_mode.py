"""The "prefixes from interfaces" mode of update-nautobot-prefix.

Reads the parent prefix of every IP address on a device's interfaces (from the ``nautobot``
attribute bag, ``interfaces[].ip_addresses[].parent``) and adds the device's location to each
prefix; the shared engine is ``workflow_steps/common/device_location_sync.py``.
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

_STEP_ID = "update-nautobot-prefix"


def _prefix_ref(raw: Any) -> SyncRef | None:
    if not isinstance(raw, dict):
        return None
    prefix_id = uuid_or_none(raw.get("id"))
    if prefix_id is None:
        return None
    namespace = raw.get("namespace")
    return SyncRef(
        id=prefix_id,
        preview={
            "prefix_id": prefix_id,
            "prefix": str(raw.get("prefix") or ""),
            "namespace": str(namespace.get("name") or "") if isinstance(namespace, dict) else "",
        },
    )


def _interface_prefixes(bag: dict[str, Any]) -> list[SyncRef]:
    """Every distinct parent prefix of the IP addresses on the bag's interfaces."""
    found: dict[str, SyncRef] = {}
    for interface in bag.get("interfaces") or []:
        if not isinstance(interface, dict):
            continue
        addresses = interface.get("ip_addresses")
        for address in addresses if isinstance(addresses, list) else []:
            ref = _prefix_ref(address.get("parent")) if isinstance(address, dict) else None
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
    async def write(prefix_id: str, location_id: str) -> bool:
        return await common.update_prefix(
            prefix_id, {}, locations=[location_id], locations_mode="add"
        )

    async def check(prefix_id: str, location_id: str) -> bool:
        return bool(await common.missing_prefix_locations(prefix_id, [location_id]))

    spec = LocationSyncSpec(
        step_id=_STEP_ID,
        counts_key="update_prefix_counts",
        noun="prefixes",
        extract=_interface_prefixes,
        write=write,
        check=check,
    )
    return await run_location_sync(spec, context=context, node_id=node_id, dry_run=dry_run)

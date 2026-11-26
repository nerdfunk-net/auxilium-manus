"""Write one Nautobot object once per distinct change, however many devices resolve to it.

Manual mode of ``update-nautobot-vlan`` (Update VLAN) and ``update-nautobot-prefix`` (Update IP
Prefix) resolves every device on its own. With a fixed target (a ``vlan_id`` / ``prefix_id`` or a
fixed ``vid`` / ``prefix``) all devices resolve to the same object and the same values, so N
concurrent writes raced for one assignment row and Nautobot refused all but one (W5-01, D6).

Items are grouped by the change they ask for (``group_of``); each group is written once and every
device of the group gets that result. Groups of the same object (``target_of``) run one after the
other, so two devices that ask for different values of one object cannot interleave their
location writes; different objects run concurrently behind ``gate``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Hashable, Sequence

from models.workflow_context import DeviceContext
from workflow_steps.common.device_outcomes import fail_device_with_error

# (outcome handle, device, whether the write changed the object)
WriteResult = tuple[str, DeviceContext, bool]


def share_result(result: WriteResult, member: DeviceContext) -> WriteResult:
    """The group's ``result`` as seen by another ``member`` device of the same group."""
    bucket, written, changed = result
    if bucket == "success":
        return bucket, member, changed
    # The failure the write recorded is the group's; the member keeps its own history.
    return bucket, fail_device_with_error(member, written.errors[-1]), False


async def write_once_per_group[T](
    items: Sequence[T],
    *,
    target_of: Callable[[T], Hashable],
    group_of: Callable[[T], Hashable],
    device_of: Callable[[T], DeviceContext],
    write: Callable[[T], Awaitable[WriteResult]],
    gate: asyncio.Semaphore,
) -> list[WriteResult]:
    """Results aligned with ``items``; ``write`` runs for the first item of each group only."""
    targets: dict[Hashable, dict[Hashable, list[int]]] = {}
    for index, item in enumerate(items):
        targets.setdefault(target_of(item), {}).setdefault(group_of(item), []).append(index)

    results: list[WriteResult | None] = [None] * len(items)

    async def run_target(groups: dict[Hashable, list[int]]) -> None:
        for members in groups.values():
            async with gate:
                result = await write(items[members[0]])
            for index in members:
                results[index] = (
                    result if index == members[0] else share_result(result, device_of(items[index]))
                )

    await asyncio.gather(*[run_target(groups) for groups in targets.values()])
    return [result for result in results if result is not None]

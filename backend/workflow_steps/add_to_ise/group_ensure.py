"""Create missing ISE network device groups (NDGs) before a device references them.

ISE rejects a device whose ``NetworkDeviceGroupList`` names a group that does not
exist. A group name is a ``#``-delimited path (``Location#All Locations#Test``) in
which every ancestor must exist too, so :meth:`DeviceGroupEnsurer.ensure` walks
the path from the root and creates each missing level.

A new root category is only creatable in ISE's ``foo#foo`` form (see
``ISENetworkDeviceGroupService.create_root_group``); any other missing two-segment
path (e.g. a misspelt ``Locations#All Locations``) is reported as an error rather
than guessed at.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from services.ise.common.exceptions import ISEValidationError

if TYPE_CHECKING:
    from services.ise.network_device_group_service import ISENetworkDeviceGroupService

logger = logging.getLogger(__name__)

_SEPARATOR = "#"
_ALREADY_EXISTS_MARKER = "already exist"


class DeviceGroupEnsurer:
    """Ensures groups exist, remembering verified paths for the rest of the run."""

    def __init__(self, group_service: ISENetworkDeviceGroupService) -> None:
        self._group_service = group_service
        self._known: set[str] = set()

    async def ensure(self, full_name: str) -> None:
        """Make sure *full_name* and all its ancestors exist in ISE.

        Raises ``ISEValidationError`` for a malformed or uncreatable name and
        lets ``ISEAPIError`` (connectivity/auth) propagate.
        """
        if full_name in self._known:
            return
        segments = [segment.strip() for segment in full_name.split(_SEPARATOR)]
        if len(segments) < 2 or not all(segments):
            raise ISEValidationError(
                f"'{full_name}' is not a full group path such as 'Location#All Locations#Test'"
            )
        for depth in range(2, len(segments) + 1):
            path = _SEPARATOR.join(segments[:depth])
            if path in self._known:
                continue
            if await self._group_service.get_group_by_name(path) is None:
                await self._create(segments, depth)
            self._known.add(path)

    async def _create(self, segments: list[str], depth: int) -> None:
        path = _SEPARATOR.join(segments[:depth])
        if depth == 2 and segments[0] != segments[1]:
            raise ISEValidationError(
                f"group '{path}' does not exist and a new top-level group must be named "
                f"'{segments[0]}#{segments[0]}'"
            )
        try:
            if depth == 2:
                await self._group_service.create_root_group(name=segments[0], description=None)
            else:
                await self._group_service.create_child_group(
                    name=segments[depth - 1],
                    description=None,
                    parent_group=_SEPARATOR.join(segments[: depth - 1]),
                )
        except ISEValidationError as exc:
            # Lost a race with another writer: the group now exists, which is the goal.
            if _ALREADY_EXISTS_MARKER not in str(exc).lower():
                raise
        logger.info("add-to-ise: created ISE network device group '%s'", path)

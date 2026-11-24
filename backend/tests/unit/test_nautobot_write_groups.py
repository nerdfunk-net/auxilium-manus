"""W5-01 (D6): devices that resolve to one Nautobot object are written once.

A fixed ``vlan_id`` / ``prefix_id`` makes every device of the context resolve to the same object
and values. The fake ``update_*`` below behaves like Nautobot's assignment table: it reads, yields
to the event loop, then adds the location, and a second add of the same pair is refused. Before the
fix N concurrent writes raced and N-1 devices failed although the end state was what was asked for.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.workflow_context import DeviceStatus
from services.nautobot.common.exceptions import NautobotAPIError
from tests.unit._step_helpers import call_step, make_context, make_device, make_run
from workflow_steps.common import nautobot_plan_fields as plan_fields
from workflow_steps.common.nautobot_write_groups import write_once_per_group
from workflow_steps.update_nautobot_prefix import executor as prefix_mod
from workflow_steps.update_nautobot_vlan import executor as vlan_mod

pytestmark = pytest.mark.asyncio

_VLAN = "55555555-5555-5555-5555-555555555555"
_PFX = "75555555-5555-5555-5555-555555555555"
_PFX2 = "76565656-5656-5656-5656-565656565656"
_STATUS = "44444444-4444-4444-4444-444444444444"
_LOC_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_LOC_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


class _AssignmentTable:
    """Records writes; a duplicate (object, location) add is refused like Nautobot does."""

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.assigned: set[tuple[str, str]] = set()
        self.calls: list[tuple[str, dict[str, str], tuple[str, ...]]] = []
        self._fail_with = fail_with

    async def write(
        self, object_id: str, fields: dict[str, str], *, locations: tuple[str, ...], **_: Any
    ) -> bool:
        self.calls.append((object_id, dict(fields), tuple(locations)))
        if self._fail_with is not None:
            raise self._fail_with
        missing = [loc for loc in locations if (object_id, loc) not in self.assigned]
        await asyncio.sleep(0)  # every other device reads the same state before anyone writes
        for loc in missing:
            if (object_id, loc) in self.assigned:
                raise NautobotAPIError("duplicate assignment")
            self.assigned.add((object_id, loc))
        return bool(missing)


def _vlan_common(table: _AssignmentTable, *, find: list[str] | None = None) -> MagicMock:
    common = MagicMock()
    common.resolve_status_id = AsyncMock(return_value=_STATUS)
    common.resolve_location_id_strict = AsyncMock(
        side_effect=lambda name: {"A": _LOC_A, "B": _LOC_B}[name]
    )
    common.find_vlans = AsyncMock(return_value=find or [_VLAN])
    common.update_vlan = table.write
    return common


def _prefix_common(table: _AssignmentTable, *, find: list[str] | None = None) -> MagicMock:
    common = MagicMock()
    common.resolve_status_id = AsyncMock(return_value=_STATUS)
    common.resolve_location_id_strict = AsyncMock(
        side_effect=lambda name: {"A": _LOC_A, "B": _LOC_B}[name]
    )
    common.find_prefixes = AsyncMock(return_value=find or [_PFX])
    common.update_prefix = table.write
    return common


async def _run(mod: Any, common: MagicMock, config: dict[str, Any], *names: str):
    context = make_context([make_device(name) for name in names])
    with patch.object(mod, "_bind_nautobot", return_value=mod._Bound(common=common)):
        outcomes = await call_step(mod.execute, config, context, run=make_run())
    by_name = {outcome.name: outcome.context for outcome in outcomes}
    return by_name, by_name["success"].metadata


_VLAN_CFG = {"nautobot_source_id": "s", "vlan_id": _VLAN, "locations": "A", "locations_mode": "add"}
_PREFIX_CFG = {
    "nautobot_source_id": "s",
    "prefix_id": _PFX,
    "locations": "A",
    "locations_mode": "add",
}


@pytest.mark.parametrize(
    ("mod", "make_common", "config", "counts_key"),
    [
        (vlan_mod, _vlan_common, _VLAN_CFG, "node-1.update_vlan_counts"),
        (prefix_mod, _prefix_common, _PREFIX_CFG, "node-1.update_prefix_counts"),
    ],
    ids=["update-nautobot-vlan", "update-nautobot-prefix"],
)
class TestFixedTargetManyDevices:
    async def test_five_devices_one_object_are_written_once(
        self, mod: Any, make_common: Any, config: dict[str, Any], counts_key: str
    ) -> None:
        table = _AssignmentTable()
        out, metadata = await _run(mod, make_common(table), config, *"abcde")
        assert len(table.calls) == 1
        assert sorted(out["success"].devices) == list("abcde")
        assert out["failure"].devices == {}
        assert metadata[counts_key] == {"updated": 5, "unchanged": 0, "failed": 0}

    async def test_a_failed_write_fails_every_device_of_the_group(
        self, mod: Any, make_common: Any, config: dict[str, Any], counts_key: str
    ) -> None:
        table = _AssignmentTable(fail_with=NautobotAPIError("boom"))
        out, _ = await _run(mod, make_common(table), config, "a", "b", "c")
        assert len(table.calls) == 1
        assert sorted(out["failure"].devices) == ["a", "b", "c"]
        for device in out["failure"].devices.values():
            assert device.status is DeviceStatus.FAILED
            assert [error.code for error in device.errors] == ["nautobotapierror"]

    async def test_a_rerun_reports_unchanged_for_every_device(
        self, mod: Any, make_common: Any, config: dict[str, Any], counts_key: str
    ) -> None:
        table = _AssignmentTable()
        table.assigned.add((_VLAN if mod is vlan_mod else _PFX, _LOC_A))
        out, metadata = await _run(mod, make_common(table), config, "a", "b")
        assert sorted(out["success"].devices) == ["a", "b"]
        assert metadata[counts_key] == {"updated": 0, "unchanged": 2, "failed": 0}


class TestSameObjectDifferentValues:
    async def test_two_value_groups_of_one_object_do_not_interleave(self) -> None:
        # {name} differs per device: two groups for one VLAN; the second sees the first's row.
        table = _AssignmentTable()
        common = _vlan_common(table)
        config = {**_VLAN_CFG, "status": "", "description": "{name}"}
        with patch.object(
            plan_fields,
            "resolve_update_field_expression",
            side_effect=lambda **kw: (
                kw["device"].name if kw["field_key"] == "description" else kw["raw_value"]
            ),
        ):
            out, _ = await _run(vlan_mod, common, config, "a", "b")
        assert [call[1] for call in table.calls] == [{"description": "a"}, {"description": "b"}]
        assert sorted(out["success"].devices) == ["a", "b"]

    async def test_different_objects_are_written_separately(self) -> None:
        table = _AssignmentTable()
        common = _prefix_common(table)
        ids = iter([[_PFX], [_PFX2]])
        common.find_prefixes = AsyncMock(side_effect=lambda *_: next(ids))
        config = {
            "nautobot_source_id": "s",
            "prefix": "{p}",
            "locations": "A",
            "locations_mode": "add",
        }
        with patch.object(
            plan_fields,
            "resolve_update_field_expression",
            side_effect=lambda **kw: {
                "prefix": "10.0.0.0/24" if kw["device"].name == "a" else "10.0.1.0/24"
            }.get(kw["field_key"], kw["raw_value"]),
        ):
            out, _ = await _run(prefix_mod, common, config, "a", "b")
        assert sorted(call[0] for call in table.calls) == sorted([_PFX, _PFX2])
        assert sorted(out["success"].devices) == ["a", "b"]


class TestWriteOncePerGroup:
    async def test_results_stay_aligned_with_items(self) -> None:
        devices = [make_device(name) for name in "abc"]
        seen: list[str] = []

        async def write(item: tuple[str, str]) -> tuple[str, Any, bool]:
            seen.append(item[0])
            return "success", devices[ord(item[0]) - ord("a")], item[1] == "x"

        results = await write_once_per_group(
            [("a", "x"), ("b", "y"), ("c", "x")],
            target_of=lambda item: "same",
            group_of=lambda item: item[1],
            device_of=lambda item: devices[ord(item[0]) - ord("a")],
            write=write,
            gate=asyncio.Semaphore(2),
        )
        assert seen == ["a", "b"]
        assert [(bucket, device.id, changed) for bucket, device, changed in results] == [
            ("success", "a", True),
            ("success", "b", False),
            ("success", "c", True),
        ]

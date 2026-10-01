"""Tests for DeviceGroupEnsurer (mocked group service, no network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.ise.common.exceptions import ISEValidationError
from workflow_steps.add_to_ise.group_ensure import DeviceGroupEnsurer


def _service(existing: set[str]) -> MagicMock:
    service = MagicMock()
    service.get_group_by_name = AsyncMock(
        side_effect=lambda name: {"NetworkDeviceGroup": {}} if name in existing else None
    )
    service.create_child_group = AsyncMock(return_value={})
    service.create_root_group = AsyncMock(return_value={})
    return service


class DeviceGroupEnsurerTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_every_missing_level_top_down(self) -> None:
        service = _service({"Location#All Locations"})
        await DeviceGroupEnsurer(service).ensure("Location#All Locations#EU#Berlin")
        calls = [c.kwargs for c in service.create_child_group.await_args_list]
        self.assertEqual(
            calls,
            [
                {"name": "EU", "description": None, "parent_group": "Location#All Locations"},
                {
                    "name": "Berlin",
                    "description": None,
                    "parent_group": "Location#All Locations#EU",
                },
            ],
        )

    async def test_new_root_category_uses_doubled_name(self) -> None:
        service = _service(set())
        await DeviceGroupEnsurer(service).ensure("foo#foo#bar")
        service.create_root_group.assert_awaited_once_with(name="foo", description=None)
        service.create_child_group.assert_awaited_once_with(
            name="bar", description=None, parent_group="foo#foo"
        )

    async def test_uncreatable_root_raises(self) -> None:
        service = _service(set())
        with self.assertRaises(ISEValidationError):
            await DeviceGroupEnsurer(service).ensure("Locations#All Locations")
        service.create_root_group.assert_not_called()

    async def test_single_segment_name_raises(self) -> None:
        with self.assertRaises(ISEValidationError):
            await DeviceGroupEnsurer(_service(set())).ensure("Test")

    async def test_verified_paths_are_cached(self) -> None:
        service = _service({"Location#All Locations", "Location#All Locations#Test"})
        ensurer = DeviceGroupEnsurer(service)
        await ensurer.ensure("Location#All Locations#Test")
        calls_after_first = service.get_group_by_name.await_count
        await ensurer.ensure("Location#All Locations#Test")
        self.assertEqual(service.get_group_by_name.await_count, calls_after_first)

    async def test_already_exists_on_create_is_tolerated(self) -> None:
        service = _service({"Location#All Locations"})
        service.create_child_group = AsyncMock(side_effect=ISEValidationError("Already Exists"))
        await DeviceGroupEnsurer(service).ensure("Location#All Locations#Test")

    async def test_other_validation_error_propagates(self) -> None:
        service = _service({"Location#All Locations"})
        service.create_child_group = AsyncMock(side_effect=ISEValidationError("bad"))
        with self.assertRaises(ISEValidationError):
            await DeviceGroupEnsurer(service).ensure("Location#All Locations#Test")

"""Tests for services/nautobot/managers/location_assignments.py (shared VLAN / prefix helpers)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.common.exceptions import NautobotAPIError
from services.nautobot.managers.location_assignments import (
    PartialUpdateError,
    apply_locations,
    missing_locations,
)

_OWNER = "55555555-5555-5555-5555-555555555555"
_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_ROW1 = "11111111-1111-1111-1111-111111111111"
_ROW2 = "22222222-2222-2222-2222-222222222222"
_ENDPOINT = "ipam/vlan-location-assignments/"


def _api(rows: list[dict], *, fail_on: str | None = None):
    nautobot = MagicMock()
    calls: list[tuple[str, str, object]] = []

    async def rest_request(*, endpoint, method="GET", data=None):
        calls.append((method, endpoint, data))
        if method == fail_on:
            raise RuntimeError("boom")
        if method == "GET":
            return {"results": rows, "next": None}
        return {}

    nautobot.rest_request = AsyncMock(side_effect=rest_request)
    nautobot.calls = calls
    return nautobot


def _row(row_id: str, location: str) -> dict:
    return {"id": row_id, "location": {"id": location}}


def _writes(nautobot) -> list[tuple[str, str]]:
    return [(m, e) for m, e, _ in nautobot.calls if m != "GET"]


class RowIdTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_row_id_that_is_not_a_uuid_is_never_put_in_a_delete_path(self) -> None:
        hostile = "../../dcim/devices/11111111-1111-1111-1111-111111111111"
        nautobot = _api([_row(hostile, _A)])
        with self.assertRaises(NautobotAPIError):
            await apply_locations(nautobot, _ENDPOINT, "vlan", _OWNER, [_B], "replace")
        self.assertEqual(_writes(nautobot), [])

    async def test_a_bad_row_id_is_found_before_any_write(self) -> None:
        # The POST for _B would be fine, but the DELETE row id is bad: nothing may be written.
        nautobot = _api([_row("not-a-uuid", _A)])
        with self.assertRaises(NautobotAPIError):
            await apply_locations(nautobot, _ENDPOINT, "vlan", _OWNER, [_B], "replace")
        self.assertEqual(_writes(nautobot), [])

    async def test_a_bad_row_id_does_not_matter_for_a_read(self) -> None:
        nautobot = _api([_row("not-a-uuid", _A)])
        self.assertEqual(
            await missing_locations(nautobot, _ENDPOINT, "vlan", _OWNER, [_A, _B]), [_B]
        )

    async def test_a_row_id_of_a_kept_location_is_not_checked(self) -> None:
        nautobot = _api([_row("not-a-uuid", _A)])
        self.assertFalse(await apply_locations(nautobot, _ENDPOINT, "vlan", _OWNER, [_A], "add"))


class RequestedLocationTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_location_that_is_not_a_uuid_is_refused_before_any_request(self) -> None:
        nautobot = _api([])
        with self.assertRaises(ValueError):
            await apply_locations(nautobot, _ENDPOINT, "vlan", _OWNER, ["../x"], "add")
        self.assertEqual(nautobot.calls, [])


class DuplicateRowTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_row_of_a_location_that_goes_is_deleted(self) -> None:
        nautobot = _api([_row(_ROW1, _A), _row(_ROW2, _A)])
        self.assertTrue(await apply_locations(nautobot, _ENDPOINT, "vlan", _OWNER, [_B], "replace"))
        deletes = sorted(e for m, e in _writes(nautobot) if m == "DELETE")
        self.assertEqual(deletes, [f"{_ENDPOINT}{_ROW1}/", f"{_ENDPOINT}{_ROW2}/"])

    async def test_remove_mode_deletes_all_rows_of_the_location(self) -> None:
        nautobot = _api([_row(_ROW1, _A), _row(_ROW2, _A)])
        await apply_locations(nautobot, _ENDPOINT, "vlan", _OWNER, [_A], "remove")
        self.assertEqual(len([1 for m, _ in _writes(nautobot) if m == "DELETE"]), 2)

    async def test_a_kept_location_with_two_rows_is_left_alone(self) -> None:
        nautobot = _api([_row(_ROW1, _A), _row(_ROW2, _A)])
        self.assertFalse(await apply_locations(nautobot, _ENDPOINT, "vlan", _OWNER, [_A], "add"))
        self.assertEqual(_writes(nautobot), [])


class PartialUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_failure_after_a_write_is_partial(self) -> None:
        nautobot = _api([_row(_ROW1, _A)], fail_on="DELETE")
        with self.assertRaises(PartialUpdateError):
            await apply_locations(nautobot, _ENDPOINT, "vlan", _OWNER, [_B], "replace")


if __name__ == "__main__":
    unittest.main()

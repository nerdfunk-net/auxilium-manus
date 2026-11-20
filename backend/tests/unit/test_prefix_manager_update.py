"""Tests for PrefixManager.update_prefix / find_prefixes / missing_locations."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import unquote

from services.nautobot.managers.location_assignments import PartialUpdateError
from services.nautobot.managers.prefix_manager import PrefixManager

_PFX = "55555555-5555-5555-5555-555555555555"
_NS = "66666666-6666-6666-6666-666666666666"
_STATUS = "44444444-4444-4444-4444-444444444444"
_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_RA = "11111111-1111-1111-1111-111111111111"
_RB = "22222222-2222-2222-2222-222222222222"


def _manager(
    current: dict | None = None,
    assigned: dict[str, str] | None = None,
    fail_post=False,
    prefix_rows: list[dict] | None = None,
):
    nautobot = MagicMock()
    calls: list[tuple[str, str, object]] = []

    async def rest_request(*, endpoint, method="GET", data=None):
        calls.append((method, endpoint, data))
        if method == "POST" and fail_post:
            raise RuntimeError("refused")
        if method != "GET":
            return {}
        if "prefix-location-assignments" in endpoint:
            rows = [{"id": rid, "location": {"id": loc}} for loc, rid in (assigned or {}).items()]
            return {"results": rows, "next": None}
        if "ipam/prefixes/?" in endpoint:
            if prefix_rows is not None:
                return {"results": prefix_rows, "next": None}
            return {"count": 1, "results": [{"id": _PFX, "prefix": "10.0.0.0/24"}], "next": None}
        return current if current is not None else {"status": {"id": _STATUS}, "description": ""}

    nautobot.rest_request = AsyncMock(side_effect=rest_request)
    nautobot.calls = calls
    network = MagicMock()
    network.resolve_namespace_id = AsyncMock(return_value=_NS)
    return PrefixManager(nautobot, network, MagicMock()), nautobot


def _kinds(nautobot, method: str) -> list[tuple[str, object]]:
    return [(e, d) for m, e, d in nautobot.calls if m == method]


class FindPrefixesTests(unittest.IsolatedAsyncioTestCase):
    async def test_finds_by_prefix_and_namespace(self) -> None:
        manager, nautobot = _manager()
        self.assertEqual(await manager.find_prefixes("10.0.0.0/24", _NS), [_PFX])
        endpoint = nautobot.calls[0][1]
        self.assertIn("prefix=10.0.0.0%2F24", endpoint)
        self.assertIn(f"namespace={_NS}", endpoint)


class FindPrefixesCanonicalTests(unittest.IsolatedAsyncioTestCase):
    async def test_searches_with_the_canonical_form_nautobot_stores(self) -> None:
        for typed in ("2001:DB8::/32", "2001:0db8:0000::/32"):
            manager, nautobot = _manager(prefix_rows=[{"id": _PFX, "prefix": "2001:db8::/32"}])
            self.assertEqual(await manager.find_prefixes(typed, _NS), [_PFX], typed)
            self.assertIn("2001:db8::/32", unquote(nautobot.calls[0][1]), typed)

    async def test_a_row_for_another_network_is_not_returned(self) -> None:
        rows = [
            {"id": _PFX, "prefix": "10.0.0.0/24"},
            {"id": "99999999-9999-9999-9999-999999999999", "prefix": "10.0.0.0/25"},
        ]
        manager, _ = _manager(prefix_rows=rows)
        self.assertEqual(await manager.find_prefixes("10.0.0.0/24", _NS), [_PFX])

    async def test_a_row_without_a_prefix_is_not_trusted(self) -> None:
        manager, _ = _manager(prefix_rows=[{"id": _PFX}])
        self.assertEqual(await manager.find_prefixes("10.0.0.0/24", _NS), [])

    async def test_a_row_is_compared_as_a_network_not_as_text(self) -> None:
        manager, _ = _manager(prefix_rows=[{"id": _PFX, "prefix": "2001:DB8::/32"}])
        self.assertEqual(await manager.find_prefixes("2001:db8::/32", _NS), [_PFX])

    async def test_text_that_is_not_a_network_is_refused(self) -> None:
        manager, nautobot = _manager()
        for bad in ("nope", "10.0.0.1/24", ""):
            with self.assertRaises(ValueError, msg=bad):
                await manager.find_prefixes(bad, _NS)
        self.assertEqual(nautobot.calls, [])


class UpdatePrefixTests(unittest.IsolatedAsyncioTestCase):
    async def test_patches_only_differing_fields(self) -> None:
        manager, nautobot = _manager()
        changed = await manager.update_prefix(_PFX, {"status": _STATUS, "description": "lan"})
        self.assertTrue(changed)
        self.assertEqual(_kinds(nautobot, "PATCH")[0][1], {"description": "lan"})

    async def test_unchanged_writes_nothing(self) -> None:
        manager, nautobot = _manager()
        self.assertFalse(await manager.update_prefix(_PFX, {"status": _STATUS}))
        self.assertEqual(_kinds(nautobot, "PATCH"), [])

    async def test_add_locations_posts_missing_assignments(self) -> None:
        manager, nautobot = _manager(assigned={_A: _RA})
        changed = await manager.update_prefix(_PFX, {}, locations=[_A, _B], locations_mode="add")
        self.assertTrue(changed)
        posts = _kinds(nautobot, "POST")
        self.assertEqual(
            posts, [("ipam/prefix-location-assignments/", {"prefix": _PFX, "location": _B})]
        )
        self.assertEqual(_kinds(nautobot, "DELETE"), [])

    async def test_replace_deletes_surplus_assignments(self) -> None:
        manager, nautobot = _manager(assigned={_A: _RA, _B: _RB})
        await manager.update_prefix(_PFX, {}, locations=[_B], locations_mode="replace")
        self.assertEqual(
            _kinds(nautobot, "DELETE"), [(f"ipam/prefix-location-assignments/{_RA}/", None)]
        )

    async def test_second_write_failing_after_fields_is_partial(self) -> None:
        manager, _ = _manager(fail_post=True)
        with self.assertRaises(PartialUpdateError) as ctx:
            await manager.update_prefix(
                _PFX, {"description": "x"}, locations=[_A], locations_mode="add"
            )
        self.assertEqual(ctx.exception.applied, ("fields",))

    async def test_rejects_non_uuid_and_bad_mode(self) -> None:
        manager, _ = _manager()
        with self.assertRaises(ValueError):
            await manager.update_prefix("nope", {"description": "x"})
        with self.assertRaises(ValueError):
            await manager.update_prefix(_PFX, {}, locations=[_A], locations_mode="merge")  # type: ignore[arg-type]


class MissingLocationsTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_only(self) -> None:
        manager, nautobot = _manager(assigned={_A: _RA})
        self.assertEqual(await manager.missing_locations(_PFX, [_A, _B]), [_B])
        self.assertEqual({m for m, _, _ in nautobot.calls}, {"GET"})


if __name__ == "__main__":
    unittest.main()

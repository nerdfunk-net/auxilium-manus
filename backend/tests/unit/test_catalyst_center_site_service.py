"""Tests for CatalystCenterSiteService (site list + site membership -> device ids).

Shapes verified live on the DevNet sandbox: GET /site -> {"response": [{id, name,
siteNameHierarchy}]}; GET /membership/{id} -> {"site": {...}, "device": [{"response":
[{instanceUuid, hostname, ...}]}]} with offset/limit paging, and an *HTTP 200* error body
({"response": {"errorCode": ...}}) for a bad id.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterValidationError,
)
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.catalyst_center.site_service import (
    MAX_TARGET_SITES,
    SITE_PAGE_SIZE,
    CatalystCenterSiteService,
)

SITE = "/dna/intent/api/v1/site"
MEMBERSHIP = "/dna/intent/api/v1/membership"


def _creds() -> CatalystCenterCredentials:
    return CatalystCenterCredentials("https://10.10.20.85", "admin", "pw")


def _site(i: int, hierarchy: str) -> dict:
    return {"id": f"site-{i}", "name": hierarchy.rsplit("/", 1)[-1], "siteNameHierarchy": hierarchy}


def _members(*ids: str) -> dict:
    return {"site": {"response": []}, "device": [{"response": [{"instanceUuid": i} for i in ids]}]}


TREE = [
    _site(1, "Global"),
    _site(2, "Global/EMEA"),
    _site(3, "Global/EMEA/Berlin"),
    _site(4, "Global/EMEAX"),
    _site(5, "Global/APAC"),
]


def _client(sites=None, members=None) -> AsyncMock:
    """Fake controller: sites list + per-site membership keyed by site id."""
    members = members or {}
    client = AsyncMock()

    async def request(creds, method, path, *, params=None, json=None):
        if path == SITE:
            return {"response": sites if sites is not None else TREE}
        if path.startswith(MEMBERSHIP + "/"):
            site_id = path.rsplit("/", 1)[-1]
            return members.get(site_id, _members())
        raise AssertionError(f"unexpected path {path}")

    client.request.side_effect = request
    return client


def _service(client: AsyncMock) -> CatalystCenterSiteService:
    return CatalystCenterSiteService(client, _creds())


def _membership_calls(client: AsyncMock) -> list[str]:
    return [c.args[2] for c in client.request.await_args_list if c.args[2].startswith(MEMBERSHIP)]


class ListSitesTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_site_fields(self) -> None:
        sites = await _service(_client()).list_sites()
        self.assertEqual(len(sites), 5)
        berlin = next(s for s in sites if s.name == "Berlin")
        self.assertEqual(berlin.id, "site-3")
        self.assertEqual(berlin.name_hierarchy, "Global/EMEA/Berlin")

    async def test_sends_paging_params(self) -> None:
        client = _client()
        await _service(client).list_sites()
        self.assertEqual(
            client.request.await_args.kwargs["params"], {"offset": 1, "limit": SITE_PAGE_SIZE}
        )

    async def test_pages_until_short_page(self) -> None:
        first = [_site(i, f"Global/S{i}") for i in range(SITE_PAGE_SIZE)]
        client = AsyncMock()
        client.request.side_effect = [
            {"response": first},
            {"response": [_site(9999, "Global/Last")]},
        ]
        sites = await _service(client).list_sites()
        self.assertEqual(len(sites), SITE_PAGE_SIZE + 1)
        self.assertEqual(
            client.request.await_args_list[1].kwargs["params"]["offset"], 1 + SITE_PAGE_SIZE
        )

    async def test_stops_when_a_page_adds_nothing_new(self) -> None:
        page = [_site(i, f"Global/S{i}") for i in range(SITE_PAGE_SIZE)]
        client = AsyncMock()
        client.request.return_value = {"response": page}  # controller ignores offset
        sites = await _service(client).list_sites()
        self.assertEqual(len(sites), SITE_PAGE_SIZE)
        self.assertEqual(client.request.await_count, 2)

    async def test_skips_entries_without_id_or_hierarchy(self) -> None:
        client = _client(sites=[{"id": "x"}, {"siteNameHierarchy": "Global/A"}, _site(1, "Global")])
        self.assertEqual([s.id for s in await _service(client).list_sites()], ["site-1"])

    async def test_non_list_response_rejected(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": {"oops": 1}}
        with self.assertRaises(CatalystCenterValidationError):
            await _service(client).list_sites()


class DeviceIdsForSitesTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_selection_makes_no_requests(self) -> None:
        client = _client()
        self.assertEqual(await _service(client).device_ids_for_sites([]), frozenset())
        client.request.assert_not_awaited()

    async def test_unknown_site_is_rejected_before_any_membership_call(self) -> None:
        client = _client()
        with self.assertRaisesRegex(CatalystCenterValidationError, "Unknown site 'Global/Nope'"):
            await _service(client).device_ids_for_sites(["Global/Nope"])
        self.assertEqual(_membership_calls(client), [])

    async def test_site_names_are_case_sensitive_exact(self) -> None:
        with self.assertRaises(CatalystCenterValidationError):
            await _service(_client()).device_ids_for_sites(["global/emea"])

    async def test_children_included_by_default_with_path_boundary(self) -> None:
        client = _client(
            members={
                "site-2": _members("d-emea"),
                "site-3": _members("d-berlin"),
                "site-4": _members("d-emeax"),
            }
        )
        ids = await _service(client).device_ids_for_sites(["Global/EMEA"])
        self.assertEqual(ids, frozenset({"d-emea", "d-berlin"}))  # not Global/EMEAX
        self.assertEqual(
            sorted(_membership_calls(client)), [f"{MEMBERSHIP}/site-2", f"{MEMBERSHIP}/site-3"]
        )

    async def test_children_can_be_excluded(self) -> None:
        client = _client(members={"site-2": _members("d-emea"), "site-3": _members("d-berlin")})
        ids = await _service(client).device_ids_for_sites(["Global/EMEA"], include_children=False)
        self.assertEqual(ids, frozenset({"d-emea"}))
        self.assertEqual(_membership_calls(client), [f"{MEMBERSHIP}/site-2"])

    async def test_unions_several_sites_and_dedupes_overlap(self) -> None:
        client = _client(members={"site-3": _members("a", "b"), "site-5": _members("b", "c")})
        ids = await _service(client).device_ids_for_sites(
            ["Global/EMEA/Berlin", "Global/APAC", "Global/EMEA/Berlin"], include_children=False
        )
        self.assertEqual(ids, frozenset({"a", "b", "c"}))
        self.assertEqual(len(_membership_calls(client)), 2)  # Berlin asked once

    async def test_membership_uses_instance_uuid_then_id(self) -> None:
        client = _client(
            members={
                "site-1": {
                    "device": [
                        {"response": [{"instanceUuid": "u1"}, {"id": "i2"}, {"hostname": "x"}]}
                    ]
                }
            }
        )
        ids = await _service(client).device_ids_for_sites(["Global"], include_children=False)
        self.assertEqual(ids, frozenset({"u1", "i2"}))

    async def test_membership_pages_until_short_page(self) -> None:
        full = [f"d{i}" for i in range(SITE_PAGE_SIZE)]
        client = AsyncMock()

        async def request(creds, method, path, *, params=None, json=None):
            if path == SITE:
                return {"response": [_site(1, "Global")]}
            if params["offset"] == 1:
                return _members(*full)
            return _members("last")

        client.request.side_effect = request
        ids = await _service(client).device_ids_for_sites(["Global"], include_children=False)
        self.assertEqual(len(ids), SITE_PAGE_SIZE + 1)

    async def test_membership_stops_when_a_page_adds_nothing_new(self) -> None:
        full = [f"d{i}" for i in range(SITE_PAGE_SIZE)]
        client = AsyncMock()

        async def request(creds, method, path, *, params=None, json=None):
            if path == SITE:
                return {"response": [_site(1, "Global")]}
            return _members(*full)  # offset ignored

        client.request.side_effect = request
        ids = await _service(client).device_ids_for_sites(["Global"], include_children=False)
        self.assertEqual(len(ids), SITE_PAGE_SIZE)

    async def test_http_200_error_body_is_an_api_error(self) -> None:
        bad = {
            "site": {"response": {"errorCode": "BadRequest", "message": "NCGR10005 secret detail"}},
            "device": [
                {"response": {"errorCode": "BadRequest", "message": "NCGR10005 secret detail"}}
            ],
        }
        client = _client(members={"site-1": bad})
        with self.assertRaises(CatalystCenterAPIError) as ctx:
            await _service(client).device_ids_for_sites(["Global"], include_children=False)
        self.assertNotIn("secret detail", str(ctx.exception))

    async def test_missing_device_block_is_an_api_error(self) -> None:
        client = _client(members={"site-1": {"site": {"response": []}}})
        with self.assertRaises(CatalystCenterAPIError):
            await _service(client).device_ids_for_sites(["Global"], include_children=False)

    async def test_too_many_target_sites_rejected(self) -> None:
        sites = [_site(0, "Global")] + [
            _site(i, f"Global/S{i}") for i in range(1, MAX_TARGET_SITES + 5)
        ]
        client = _client(sites=sites)
        with self.assertRaisesRegex(CatalystCenterValidationError, "narrower"):
            await _service(client).device_ids_for_sites(["Global"])
        self.assertEqual(_membership_calls(client), [])

    async def test_unsafe_site_id_from_controller_is_rejected(self) -> None:
        client = _client(sites=[{"id": "../x", "siteNameHierarchy": "Global"}])
        with self.assertRaises(CatalystCenterValidationError):
            await _service(client).device_ids_for_sites(["Global"], include_children=False)
        self.assertEqual(_membership_calls(client), [])

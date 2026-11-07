"""``AciService.query_class_tree``: a class query that also returns selected child objects."""

from __future__ import annotations

import unittest

import httpx

from services.aci.common.exceptions import AciAPIError, AciValidationError
from tests.unit.test_aci_client_node import _creds, _Harness


def _cep(mac: str) -> dict:
    return {
        "fvCEp": {
            "attributes": {"mac": mac, "dn": f"uni/tn-T/ap-A/epg-E/cep-{mac}"},
            "children": [
                {"fvIp": {"attributes": {"addr": "10.1.1.5"}}},
                {"fvIp": {"attributes": {"addr": "10.1.1.6"}}},
                {
                    "fvRsCEpToPathEp": {
                        "attributes": {"tDn": "topology/pod-1/paths-101/pathep-[eth1/5]"}
                    }
                },
                {"fvRsOther": {"attributes": {"x": "1"}}},
            ],
        }
    }


class QueryClassTreeTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_attributes_with_the_requested_children_grouped_by_class(self) -> None:
        h = _Harness(lambda r: httpx.Response(200, json={"imdata": [_cep("AA:BB:CC:00:00:01")]}))
        try:
            rows = await h.service.query_class_tree(
                _creds(),
                "fvCEp",
                query_filter='eq(fvCEp.mac,"AA:BB:CC:00:00:01")',
                child_classes=("fvIp", "fvRsCEpToPathEp"),
            )
        finally:
            await h.http.aclose()
        (row,) = rows
        self.assertEqual(row["attributes"]["mac"], "AA:BB:CC:00:00:01")
        self.assertEqual([c["addr"] for c in row["children"]["fvIp"]], ["10.1.1.5", "10.1.1.6"])
        self.assertEqual(len(row["children"]["fvRsCEpToPathEp"]), 1)
        self.assertNotIn("fvRsOther", row["children"])  # not asked for

    async def test_sends_the_subtree_options_and_the_filter(self) -> None:
        h = _Harness(lambda r: httpx.Response(200, json={"imdata": []}))
        try:
            await h.service.query_class_tree(
                _creds(),
                "fvCEp",
                query_filter='eq(fvCEp.mac,"AA")',
                child_classes=("fvIp", "fvRsCEpToPathEp"),
            )
        finally:
            await h.http.aclose()
        call = h.requests[0]
        self.assertEqual(call.url.path, "/api/class/fvCEp.json")
        self.assertEqual(call.url.params["rsp-subtree"], "children")
        self.assertEqual(call.url.params["rsp-subtree-class"], "fvIp,fvRsCEpToPathEp")
        self.assertEqual(call.url.params["query-target-filter"], 'eq(fvCEp.mac,"AA")')

    async def test_an_object_without_children_has_empty_groups(self) -> None:
        body = {"imdata": [{"fvCEp": {"attributes": {"mac": "AA"}}}]}
        h = _Harness(lambda r: httpx.Response(200, json=body))
        try:
            (row,) = await h.service.query_class_tree(_creds(), "fvCEp", child_classes=("fvIp",))
        finally:
            await h.http.aclose()
        self.assertEqual(row, {"attributes": {"mac": "AA"}, "children": {}})

    async def test_class_names_are_validated(self) -> None:
        h = _Harness(lambda r: httpx.Response(200, json={"imdata": []}))
        try:
            with self.assertRaises(AciValidationError):
                await h.service.query_class_tree(_creds(), "fvCEp.json?x", child_classes=())
            with self.assertRaises(AciValidationError):
                await h.service.query_class_tree(_creds(), "fvCEp", child_classes=("fvIp,x",))
        finally:
            await h.http.aclose()
        self.assertEqual(h.requests, [])

    async def test_fails_instead_of_truncating(self) -> None:
        h = _Harness(lambda r: httpx.Response(200, json={"imdata": [_cep("AA:00")] * 3}))
        try:
            with self.assertRaises(AciAPIError) as caught:
                await h.service.query_class_tree(
                    _creds(), "fvCEp", child_classes=("fvIp",), max_objects=2
                )
        finally:
            await h.http.aclose()
        self.assertEqual(caught.exception.code, "too_many_objects")

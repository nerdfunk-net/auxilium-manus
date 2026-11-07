"""Node-scoped reads of the ACI client: ``query_node_class`` and ``get_node_mo``."""

from __future__ import annotations

import unittest

import httpx

from services.aci.client import LOGIN_PATH, AciService
from services.aci.common.exceptions import AciAPIError, AciValidationError
from services.aci.credentials import AciCredentials


def _creds() -> AciCredentials:
    return AciCredentials("https://10.10.20.14", "admin", "pw")


def _login() -> httpx.Response:
    return httpx.Response(200, json={"imdata": [{"aaaLogin": {"attributes": {"token": "t"}}}]})


def _objs(cls: str, start: int, count: int) -> list[dict]:
    return [{cls: {"attributes": {"id": str(start + i)}}} for i in range(count)]


class _Harness:
    def __init__(self, handler) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self._wrap))
        self.service = AciService()
        self.service._client_verify = self.service._client_no_verify = self.http

    def _wrap(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == LOGIN_PATH:
            return _login()
        self.requests.append(request)
        return self._handler(request)


class QueryNodeClassTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_the_class_under_the_node(self) -> None:
        h = _Harness(
            lambda r: httpx.Response(
                200, json={"totalCount": "2", "imdata": _objs("l1PhysIf", 0, 2)}
            )
        )
        try:
            rows = await h.service.query_node_class(_creds(), 1, 101, "l1PhysIf")
        finally:
            await h.http.aclose()
        self.assertEqual(rows, [{"id": "0"}, {"id": "1"}])
        call = h.requests[0]
        self.assertEqual(call.url.path, "/api/node/class/topology/pod-1/node-101/l1PhysIf.json")
        self.assertEqual(call.url.params["page"], "0")
        self.assertEqual(call.url.params["page-size"], "1000")

    async def test_sends_the_filter(self) -> None:
        h = _Harness(lambda r: httpx.Response(200, json={"imdata": []}))
        try:
            await h.service.query_node_class(
                _creds(), 2, 1101, "faultInst", query_filter='eq(faultInst.severity,"major")'
            )
        finally:
            await h.http.aclose()
        self.assertEqual(
            h.requests[0].url.params["query-target-filter"], 'eq(faultInst.severity,"major")'
        )
        self.assertIn("pod-2/node-1101/", h.requests[0].url.path)

    async def test_pages_until_a_short_page_like_query_class(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            page = int(request.url.params["page"])
            return httpx.Response(
                200, json={"imdata": _objs("ethpmPhysIf", page * 2, 2 if page < 2 else 1)}
            )

        h = _Harness(handler)
        try:
            rows = await h.service.query_node_class(_creds(), 1, 101, "ethpmPhysIf", page_size=2)
        finally:
            await h.http.aclose()
        self.assertEqual([r["id"] for r in rows], ["0", "1", "2", "3", "4"])

    async def test_fails_instead_of_truncating(self) -> None:
        h = _Harness(
            lambda r: httpx.Response(
                200, json={"totalCount": "999", "imdata": _objs("ethpmPhysIf", 0, 2)}
            )
        )
        try:
            with self.assertRaises(AciAPIError) as ctx:
                await h.service.query_node_class(
                    _creds(), 1, 101, "ethpmPhysIf", page_size=2, max_objects=3
                )
        finally:
            await h.http.aclose()
        self.assertEqual(ctx.exception.code, "too_many_objects")

    async def test_pod_and_node_must_be_positive_whole_numbers(self) -> None:
        h = _Harness(lambda r: httpx.Response(200, json={"imdata": []}))
        try:
            for pod, node in [
                (0, 1),
                (1, 0),
                (-1, 1),
                (1, -5),
                (True, 1),
                (1, True),
                ("1", 1),
                (1, "101"),
                (1.5, 1),
                (1, None),
            ]:
                with self.subTest(pod=pod, node=node), self.assertRaises(AciValidationError):
                    await h.service.query_node_class(_creds(), pod, node, "l1PhysIf")  # type: ignore[arg-type]
        finally:
            await h.http.aclose()
        self.assertEqual(h.requests, [])

    async def test_path_injection_through_pod_or_node_is_impossible(self) -> None:
        h = _Harness(lambda r: httpx.Response(200, json={"imdata": []}))
        try:
            for node in ("101/../../x", "101?a=b", "101#"):
                with self.subTest(node=node), self.assertRaises(AciValidationError):
                    await h.service.query_node_class(_creds(), 1, node, "l1PhysIf")  # type: ignore[arg-type]
            for name in ("", "l1 PhysIf", "a/b", "l1PhysIf.json?x=1", "../x", "1abc"):
                with self.subTest(name=name), self.assertRaises(AciValidationError):
                    await h.service.query_node_class(_creds(), 1, 101, name)
        finally:
            await h.http.aclose()
        self.assertEqual(h.requests, [])


class GetNodeMoTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_the_attributes_of_one_object(self) -> None:
        h = _Harness(
            lambda r: httpx.Response(
                200,
                json={
                    "totalCount": "1",
                    "imdata": [{"healthInst": {"attributes": {"cur": "90", "prev": "100"}}}],
                },
            )
        )
        try:
            attrs = await h.service.get_node_mo(_creds(), 1, 101, "sys/health", "healthInst")
        finally:
            await h.http.aclose()
        self.assertEqual(attrs, {"cur": "90", "prev": "100"})
        self.assertEqual(h.requests[0].url.path, "/api/mo/topology/pod-1/node-101/sys/health.json")

    async def test_an_empty_relative_dn_is_the_switch_node_itself(self) -> None:
        h = _Harness(
            lambda r: httpx.Response(
                200,
                json={"imdata": [{"fabricNode": {"attributes": {"model": "N9K-C9396PX"}}}]},
            )
        )
        try:
            attrs = await h.service.get_node_mo(_creds(), 1, 101, "", "fabricNode")
        finally:
            await h.http.aclose()
        self.assertEqual(attrs, {"model": "N9K-C9396PX"})
        self.assertEqual(h.requests[0].url.path, "/api/mo/topology/pod-1/node-101.json")

    async def test_a_missing_object_is_none(self) -> None:
        h = _Harness(lambda r: httpx.Response(200, json={"totalCount": "0", "imdata": []}))
        try:
            self.assertIsNone(
                await h.service.get_node_mo(_creds(), 1, 101, "sys/health", "healthInst")
            )
        finally:
            await h.http.aclose()

    async def test_an_object_of_another_class_is_none(self) -> None:
        h = _Harness(
            lambda r: httpx.Response(200, json={"imdata": [{"other": {"attributes": {"a": "1"}}}]})
        )
        try:
            self.assertIsNone(
                await h.service.get_node_mo(_creds(), 1, 101, "sys/health", "healthInst")
            )
        finally:
            await h.http.aclose()

    async def test_the_relative_dn_and_class_are_validated(self) -> None:
        h = _Harness(lambda r: httpx.Response(200, json={"imdata": []}))
        try:
            for rdn in ("../x", "sys/health?x=1", "sys health", "/sys/health", "sys//health", " "):
                with self.subTest(rdn=rdn), self.assertRaises(AciValidationError):
                    await h.service.get_node_mo(_creds(), 1, 101, rdn, "healthInst")
            with self.assertRaises(AciValidationError):
                await h.service.get_node_mo(_creds(), 1, 101, "sys/health", "bad name")
            with self.assertRaises(AciValidationError):
                await h.service.get_node_mo(_creds(), 0, 101, "sys/health", "healthInst")
        finally:
            await h.http.aclose()
        self.assertEqual(h.requests, [])

    async def test_an_unexpected_body_is_an_invalid_response(self) -> None:
        h = _Harness(lambda r: httpx.Response(200, json={"nope": True}))
        try:
            with self.assertRaises(AciAPIError) as ctx:
                await h.service.get_node_mo(_creds(), 1, 101, "sys/health", "healthInst")
        finally:
            await h.http.aclose()
        self.assertEqual(ctx.exception.code, "invalid_response")

    async def test_the_public_surface_stays_read_only(self) -> None:
        service = AciService()
        public = {
            n for n in dir(service) if not n.startswith("_") and callable(getattr(service, n))
        }
        self.assertEqual(
            public,
            {
                "get",
                "query_class",
                "query_class_tree",
                "query_node_class",
                "get_node_mo",
                "login_info",
                "startup",
                "shutdown",
            },
        )


if __name__ == "__main__":
    unittest.main()

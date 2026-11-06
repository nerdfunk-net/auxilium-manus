"""Edge cases of the ACI client: lifecycle, login failures, transport errors, failure mapping."""

from __future__ import annotations

import unittest
from unittest import mock

import httpx

from services.aci.client import (
    LOGIN_PATH,
    AciService,
    _session_seconds,
    _total_count,
)
from services.aci.common.exceptions import (
    AciAPIError,
    AciAuthError,
    AciNotFoundError,
    AciRateLimitError,
    AciValidationError,
)
from services.aci.credentials import AciCredentials


def _creds(**overrides) -> AciCredentials:
    base = {"base_url": "https://10.10.20.14", "username": "admin", "password": "pw-1"}
    base.update(overrides)
    return AciCredentials(**base)


def _service(handler) -> tuple[AciService, httpx.AsyncClient]:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = AciService()
    service._client_verify = service._client_no_verify = http
    return service, http


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_and_shutdown_manage_both_pools(self) -> None:
        service = AciService()
        await service.startup()
        self.assertIsNotNone(service._client_verify)
        self.assertIsNotNone(service._client_no_verify)
        service._sessions[("a", "b", "c")] = ("t", 1.0, None)
        await service.shutdown()
        self.assertIsNone(service._client_verify)
        self.assertIsNone(service._client_no_verify)
        self.assertEqual(service._sessions, {})

    async def test_works_without_startup_through_a_throwaway_client(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == LOGIN_PATH:
                return httpx.Response(
                    200,
                    json={
                        "imdata": [
                            {
                                "aaaLogin": {
                                    "attributes": {"token": "t", "refreshTimeoutSeconds": "600"}
                                }
                            }
                        ]
                    },
                )
            return httpx.Response(200, json={"imdata": []})

        real = httpx.AsyncClient
        service = AciService()
        with mock.patch(
            "services.aci.client.httpx.AsyncClient",
            lambda **kw: real(transport=httpx.MockTransport(handler)),
        ):
            self.assertEqual(await service.get(_creds(), "/api/class/a.json"), {"imdata": []})

    async def test_unsafe_url_is_rejected_before_any_request(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200)

        service, http = _service(handler)
        try:
            with self.assertRaises(AciValidationError):
                await service.get(_creds(base_url="http://169.254.169.254"), "/api/x.json")
        finally:
            await http.aclose()
        self.assertEqual(calls, [])

    async def test_verify_ssl_false_uses_the_no_verify_pool(self) -> None:
        seen: list[str] = []

        def handler_for(name: str):
            def handler(request: httpx.Request) -> httpx.Response:
                seen.append(name)
                if request.url.path == LOGIN_PATH:
                    return httpx.Response(
                        200, json={"imdata": [{"aaaLogin": {"attributes": {"token": "t"}}}]}
                    )
                return httpx.Response(200, json={"imdata": []})

            return handler

        service = AciService()
        service._client_verify = httpx.AsyncClient(transport=httpx.MockTransport(handler_for("v")))
        service._client_no_verify = httpx.AsyncClient(
            transport=httpx.MockTransport(handler_for("n"))
        )
        try:
            await service.get(_creds(verify_ssl=False), "/api/class/a.json")
        finally:
            await service._client_verify.aclose()
            await service._client_no_verify.aclose()
        self.assertEqual(set(seen), {"n"})


class LoginFailureTests(unittest.IsolatedAsyncioTestCase):
    async def _login_with(self, response: httpx.Response) -> AciAPIError:
        service, http = _service(lambda request: response)
        try:
            with self.assertRaises(AciAPIError) as ctx:
                await service.login_info(_creds())
        finally:
            await http.aclose()
        return ctx.exception

    async def test_login_server_error(self) -> None:
        exc = await self._login_with(httpx.Response(503, text="secret-detail"))
        self.assertEqual(exc.http_status, 503)
        self.assertNotIn("secret-detail", str(exc))

    async def test_login_body_not_json(self) -> None:
        exc = await self._login_with(httpx.Response(200, text="<html>"))
        self.assertEqual(exc.code, "invalid_response")

    async def test_login_body_without_aaa_login(self) -> None:
        exc = await self._login_with(httpx.Response(200, json={"imdata": []}))
        self.assertEqual(exc.code, "invalid_response")

    async def test_login_body_with_non_dict_attributes(self) -> None:
        exc = await self._login_with(
            httpx.Response(200, json={"imdata": [{"aaaLogin": {"attributes": "x"}}]})
        )
        self.assertEqual(exc.code, "invalid_response")

    async def test_login_without_token(self) -> None:
        exc = await self._login_with(
            httpx.Response(200, json={"imdata": [{"aaaLogin": {"attributes": {"token": ""}}}]})
        )
        self.assertEqual(exc.code, "invalid_response")

    async def test_login_transport_error_maps_to_api_error(self) -> None:
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        service, http = _service(boom)
        try:
            with self.assertRaises(AciAPIError) as ctx:
                await service.login_info(_creds())
        finally:
            await http.aclose()
        self.assertEqual(ctx.exception.code, "transport")

    async def test_version_is_none_when_the_login_has_no_version(self) -> None:
        service, http = _service(
            lambda request: httpx.Response(
                200, json={"imdata": [{"aaaLogin": {"attributes": {"token": "t"}}}]}
            )
        )
        try:
            info = await service.login_info(_creds())
        finally:
            await http.aclose()
        self.assertIsNone(info.version)


def _objs(cls: str, start: int, count: int) -> list[dict]:
    return [{cls: {"attributes": {"id": str(start + i)}}} for i in range(count)]


class PagingSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, handler, **kwargs):
        service, http = _service(handler)
        try:
            return await service.query_class(_creds(), "fabricNode", **kwargs)
        finally:
            await http.aclose()

    @staticmethod
    def _login() -> httpx.Response:
        return httpx.Response(200, json={"imdata": [{"aaaLogin": {"attributes": {"token": "t"}}}]})

    async def test_a_missing_or_garbage_total_count_does_not_end_paging_after_a_full_page(
        self,
    ) -> None:
        for total in ("lots", "", None, "MISSING"):
            pages: list[str] = []

            def handler(request: httpx.Request, total=total, pages=pages) -> httpx.Response:
                if request.url.path == LOGIN_PATH:
                    return self._login()
                page = int(request.url.params["page"])
                pages.append(str(page))
                body: dict = {"imdata": _objs("fabricNode", page * 2, 2 if page < 2 else 1)}
                if total != "MISSING":
                    body["totalCount"] = total
                return httpx.Response(200, json=body)

            with self.subTest(total=total):
                rows = await self._run(handler, page_size=2)
                self.assertEqual([r["id"] for r in rows], ["0", "1", "2", "3", "4"])
                self.assertEqual(pages, ["0", "1", "2"])

    async def test_a_valid_total_count_still_ends_paging_early(self) -> None:
        pages: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == LOGIN_PATH:
                return self._login()
            pages.append(request.url.params["page"])
            return httpx.Response(
                200, json={"totalCount": "2", "imdata": _objs("fabricNode", 0, 2)}
            )

        rows = await self._run(handler, page_size=2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(pages, ["0"])

    async def test_full_pages_of_unparsable_objects_still_hit_the_object_cap(self) -> None:
        requests = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == LOGIN_PATH:
                return self._login()
            requests["n"] += 1
            if requests["n"] > 200:  # a runaway loop would get here
                return httpx.Response(200, json={"imdata": [], "totalCount": "0"})
            return httpx.Response(200, json={"imdata": _objs("other", 0, 2), "totalCount": "99999"})

        service, http = _service(handler)
        try:
            with self.assertRaises(AciAPIError) as ctx:
                await service.query_class(_creds(), "fabricNode", page_size=2, max_objects=10)
        finally:
            await http.aclose()
        self.assertEqual(ctx.exception.code, "too_many_objects")
        self.assertLessEqual(requests["n"], 7)

    async def test_the_default_cap_bounds_the_requests_for_a_runaway_source(self) -> None:
        requests = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == LOGIN_PATH:
                return self._login()
            requests["n"] += 1
            return httpx.Response(
                200, json={"imdata": _objs("other", 0, 1000), "totalCount": "99999999"}
            )

        service, http = _service(handler)
        try:
            with self.assertRaises(AciAPIError):
                await service.query_class(_creds(), "fabricNode")
        finally:
            await http.aclose()
        self.assertLessEqual(requests["n"], 60)


class LoginLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_slow_fabric_does_not_block_logins_to_another_one(self) -> None:
        import asyncio

        release = asyncio.Event()
        started = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == LOGIN_PATH:
                name = json_name(request)
                if name == "slow":
                    started.set()
                    await release.wait()  # a black-holed APIC
                return httpx.Response(
                    200, json={"imdata": [{"aaaLogin": {"attributes": {"token": name}}}]}
                )
            return httpx.Response(200, json={"imdata": []})

        def json_name(request: httpx.Request) -> str:
            import json

            return json.loads(request.content)["aaaUser"]["attributes"]["name"]

        service, http = _service(handler)
        slow = asyncio.create_task(service.get(_creds(username="slow"), "/api/class/a.json"))
        try:
            await asyncio.wait_for(started.wait(), 2)
            result = await asyncio.wait_for(
                service.get(_creds(username="fast"), "/api/class/a.json"), 2
            )
            self.assertEqual(result, {"imdata": []})
            self.assertFalse(slow.done())
        finally:
            release.set()
            await slow
            await http.aclose()

    async def test_concurrent_calls_for_the_same_fabric_log_in_once(self) -> None:
        import asyncio

        logins = {"n": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == LOGIN_PATH:
                logins["n"] += 1
                await asyncio.sleep(0.05)
                return httpx.Response(
                    200, json={"imdata": [{"aaaLogin": {"attributes": {"token": "t"}}}]}
                )
            return httpx.Response(200, json={"imdata": []})

        service, http = _service(handler)
        try:
            await asyncio.gather(*(service.get(_creds(), "/api/class/a.json") for _ in range(5)))
        finally:
            await http.aclose()
        self.assertEqual(logins["n"], 1)

    async def test_shutdown_forgets_the_per_fabric_locks(self) -> None:
        service = AciService()
        await service.startup()
        service._login_lock_for(("a", "b", "c"))
        await service.shutdown()
        self.assertEqual(service._login_locks, {})


class HelperTests(unittest.TestCase):
    def test_session_seconds(self) -> None:
        self.assertEqual(_session_seconds("600"), 540.0)
        # A short APIC timeout is never cached past its real expiry.
        self.assertEqual(_session_seconds("10"), 5.0)
        self.assertEqual(_session_seconds("60"), 30.0)
        self.assertEqual(_session_seconds("0"), 0.0)
        self.assertEqual(_session_seconds(None), 240.0)  # default 300 - margin
        self.assertEqual(_session_seconds("nan"), 240.0)
        self.assertEqual(_session_seconds("inf"), 240.0)

    def test_total_count_is_none_unless_it_parses(self) -> None:
        self.assertEqual(_total_count({"totalCount": "7"}), 7)
        self.assertEqual(_total_count({"totalCount": 7}), 7)
        for body in ({"totalCount": "x"}, {}, {"totalCount": None}, {"totalCount": ""}):
            self.assertIsNone(_total_count(body))

    def test_credentials_login_name(self) -> None:
        self.assertEqual(_creds().login_name, "admin")
        self.assertEqual(_creds(login_domain="corp").login_name, "apic:corp\\admin")


class FailureMappingTests(unittest.TestCase):
    def _kind(self, exc) -> tuple[str, bool]:
        failure = exc.failure
        return failure.kind, failure.retryable

    def test_kinds(self) -> None:
        cases = [
            (AciAuthError("x", code="token_rejected"), ("auth_failed", False)),
            (
                AciAuthError("x", http_status=403, code="request_denied"),
                ("permission_denied", False),
            ),
            (AciRateLimitError("x", http_status=429), ("rate_limited", True)),
            (AciNotFoundError("x", http_status=404), ("not_found", False)),
            (AciValidationError("x", http_status=400), ("bad_request", False)),
            (AciAPIError("x", code="timeout"), ("timeout", True)),
            (AciAPIError("x", code="invalid_response"), ("invalid_response", False)),
            (AciAPIError("x", code="too_many_objects"), ("invalid_response", False)),
            (AciAPIError("x", http_status=502), ("server_error", True)),
            (AciAPIError("x", http_status=418), ("bad_request", False)),
            (AciAPIError("x"), ("unknown", False)),
        ]
        for exc, expected in cases:
            with self.subTest(exc=exc, code=exc.code):
                self.assertEqual(self._kind(exc), expected)

    def test_transport_cause_is_classified(self) -> None:
        exc = AciAPIError("x", code="transport")
        exc.__cause__ = ConnectionRefusedError()
        kind = exc.failure.kind
        self.assertIn(kind, {"refused", "unknown"})


if __name__ == "__main__":
    unittest.main()

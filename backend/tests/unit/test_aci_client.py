"""Tests for the Cisco ACI (APIC) HTTP client: login, session cookie, paging, read-only guard."""

from __future__ import annotations

import json
import unittest

import httpx

from services.aci.client import LOGIN_PATH, AciService
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


def _login_body(token: str = "tok-1", refresh: str = "600", version: str = "6.1(4h)") -> dict:
    return {
        "totalCount": "1",
        "imdata": [
            {
                "aaaLogin": {
                    "attributes": {
                        "token": token,
                        "refreshTimeoutSeconds": refresh,
                        "version": version,
                    }
                }
            }
        ],
    }


def _objects(cls: str, count: int, start: int = 0) -> list[dict]:
    return [{cls: {"attributes": {"id": str(start + i)}}} for i in range(count)]


class _Apic:
    """Scriptable fake APIC recording every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.logins = 0
        self.login_status = 200
        self.login_refresh = "600"
        self.api_responses: list[httpx.Response] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == LOGIN_PATH:
            if self.login_status != 200:
                return httpx.Response(
                    self.login_status, json={"imdata": [{"error": {"text": "secret-detail"}}]}
                )
            self.logins += 1
            return httpx.Response(
                200,
                json=_login_body(f"tok-{self.logins}", self.login_refresh),
                headers={"Set-Cookie": f"APIC-cookie=tok-{self.logins}; Path=/"},
            )
        if self.api_responses:
            return self.api_responses.pop(0)
        return httpx.Response(200, json={"totalCount": "0", "imdata": []})

    @property
    def api_calls(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path != LOGIN_PATH]


class AciClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.apic = _Apic()
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self.apic.handler))
        self.service = AciService()
        self.service._client_verify = self.http
        self.service._client_no_verify = self.http
        self.sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            self.sleeps.append(seconds)

        self.service._sleep = fake_sleep

    async def asyncTearDown(self) -> None:
        await self.http.aclose()

    # --- login and session -------------------------------------------------

    async def test_login_posts_aaa_user_and_sends_cookie_header(self) -> None:
        await self.service.get(_creds(), "/api/class/fabricNode.json")

        login = self.apic.requests[0]
        self.assertEqual(login.method, "POST")
        body = json.loads(login.content)
        self.assertEqual(body, {"aaaUser": {"attributes": {"name": "admin", "pwd": "pw-1"}}})
        self.assertEqual(self.apic.api_calls[0].headers["cookie"], "APIC-cookie=tok-1")

    async def test_login_domain_is_prefixed(self) -> None:
        await self.service.get(_creds(login_domain="corp"), "/api/class/fabricNode.json")
        body = json.loads(self.apic.requests[0].content)
        self.assertEqual(body["aaaUser"]["attributes"]["name"], "apic:corp\\admin")

    async def test_session_is_cached(self) -> None:
        await self.service.get(_creds(), "/api/class/a.json")
        await self.service.get(_creds(), "/api/class/b.json")
        self.assertEqual(self.apic.logins, 1)
        self.assertEqual(len(self.apic.api_calls), 2)

    async def test_password_change_forces_new_login(self) -> None:
        await self.service.get(_creds(), "/api/class/a.json")
        await self.service.get(_creds(password="pw-2"), "/api/class/a.json")
        self.assertEqual(self.apic.logins, 2)

    async def test_session_is_renewed_before_the_apic_timeout(self) -> None:
        self.apic.login_refresh = "60"  # APIC says: idle timeout 60 s
        await self.service.get(_creds(), "/api/class/a.json")
        key = next(iter(self.service._sessions))
        token, _, version = self.service._sessions[key]
        self.service._sessions[key] = (token, 0.0, version)  # force expiry
        await self.service.get(_creds(), "/api/class/a.json")
        self.assertEqual(self.apic.logins, 2)

    async def test_403_logs_in_again_once_and_retries(self) -> None:
        self.apic.api_responses = [
            httpx.Response(403, json={"imdata": [{"error": {"text": "Token was invalid"}}]}),
            httpx.Response(200, json={"totalCount": "0", "imdata": []}),
        ]
        await self.service.get(_creds(), "/api/class/a.json")
        self.assertEqual(self.apic.logins, 2)
        self.assertEqual(self.apic.api_calls[1].headers["cookie"], "APIC-cookie=tok-2")

    async def test_second_403_raises_auth_error(self) -> None:
        self.apic.api_responses = [httpx.Response(403), httpx.Response(403)]
        with self.assertRaises(AciAuthError) as ctx:
            await self.service.get(_creds(), "/api/class/a.json")
        self.assertEqual(ctx.exception.code, "request_denied")

    async def test_rejected_login_raises_auth_error_without_body_text(self) -> None:
        self.apic.login_status = 401
        with self.assertRaises(AciAuthError) as ctx:
            await self.service.get(_creds(), "/api/class/a.json")
        self.assertEqual(ctx.exception.code, "token_rejected")
        self.assertNotIn("secret-detail", str(ctx.exception))

    async def test_login_info_reports_the_apic_version(self) -> None:
        info = await self.service.login_info(_creds())
        self.assertEqual(info.version, "6.1(4h)")

    async def test_login_info_fresh_ignores_the_cache(self) -> None:
        await self.service.get(_creds(), "/api/class/a.json")
        await self.service.login_info(_creds(), fresh=True)
        self.assertEqual(self.apic.logins, 2)

    async def test_cookie_of_one_source_is_not_sent_for_another(self) -> None:
        await self.service.get(_creds(), "/api/class/a.json")
        await self.service.get(_creds(username="other"), "/api/class/a.json")
        second_login = [r for r in self.apic.requests if r.url.path == LOGIN_PATH][1]
        self.assertNotIn("cookie", second_login.headers)

    async def test_missing_credentials_are_rejected(self) -> None:
        with self.assertRaises(AciValidationError):
            await self.service.get(_creds(password=""), "/api/class/a.json")

    # --- read-only guard ---------------------------------------------------

    async def test_only_get_is_public(self) -> None:
        public = {
            n
            for n in dir(self.service)
            if not n.startswith("_") and callable(getattr(self.service, n))
        }
        allowed = {"get", "query_class", "query_class_tree", "query_node_class", "get_node_mo"}
        allowed |= {"login_info", "startup", "shutdown"}
        self.assertTrue(allowed >= public)

    async def test_transport_refuses_writes_other_than_login(self) -> None:
        with self.assertRaises(AciValidationError):
            await self.service._send(
                _creds(),
                "POST",
                "https://10.10.20.14/api/mo/uni.json",
                headers={},
            )
        with self.assertRaises(AciValidationError):
            await self.service._send(
                _creds(),
                "DELETE",
                "https://10.10.20.14/api/mo/uni.json",
                headers={},
            )
        self.assertEqual(self.apic.requests, [])

    # --- queries and paging ------------------------------------------------

    async def test_query_class_returns_attribute_dicts(self) -> None:
        self.apic.api_responses = [
            httpx.Response(200, json={"totalCount": "2", "imdata": _objects("fabricNode", 2)})
        ]
        rows = await self.service.query_class(_creds(), "fabricNode")
        self.assertEqual(rows, [{"id": "0"}, {"id": "1"}])
        call = self.apic.api_calls[0]
        self.assertEqual(call.url.path, "/api/class/fabricNode.json")
        self.assertEqual(call.url.params["page"], "0")
        self.assertEqual(call.url.params["page-size"], "1000")

    async def test_query_class_sends_filter(self) -> None:
        await self.service.query_class(
            _creds(), "fabricNode", query_filter='eq(fabricNode.role,"leaf")'
        )
        self.assertEqual(
            self.apic.api_calls[0].url.params["query-target-filter"],
            'eq(fabricNode.role,"leaf")',
        )

    async def test_query_class_pages_until_a_short_page(self) -> None:
        self.apic.api_responses = [
            httpx.Response(200, json={"totalCount": "5", "imdata": _objects("fabricNode", 2)}),
            httpx.Response(200, json={"totalCount": "5", "imdata": _objects("fabricNode", 2, 2)}),
            httpx.Response(200, json={"totalCount": "5", "imdata": _objects("fabricNode", 1, 4)}),
        ]
        rows = await self.service.query_class(_creds(), "fabricNode", page_size=2)
        self.assertEqual([r["id"] for r in rows], ["0", "1", "2", "3", "4"])
        self.assertEqual([c.url.params["page"] for c in self.apic.api_calls], ["0", "1", "2"])

    async def test_query_class_stops_when_total_count_is_reached(self) -> None:
        self.apic.api_responses = [
            httpx.Response(200, json={"totalCount": "2", "imdata": _objects("fabricNode", 2)}),
        ]
        rows = await self.service.query_class(_creds(), "fabricNode", page_size=2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(self.apic.api_calls), 1)

    async def test_query_class_fails_instead_of_truncating(self) -> None:
        self.apic.api_responses = [
            httpx.Response(200, json={"totalCount": "99", "imdata": _objects("fabricNode", 2)}),
            httpx.Response(200, json={"totalCount": "99", "imdata": _objects("fabricNode", 2, 2)}),
        ]
        with self.assertRaises(AciAPIError) as ctx:
            await self.service.query_class(_creds(), "fabricNode", page_size=2, max_objects=3)
        self.assertEqual(ctx.exception.code, "too_many_objects")

    async def test_query_class_ignores_objects_of_other_classes(self) -> None:
        self.apic.api_responses = [
            httpx.Response(
                200,
                json={
                    "totalCount": "2",
                    "imdata": [*_objects("fabricNode", 1), *_objects("other", 1, 1)],
                },
            )
        ]
        rows = await self.service.query_class(_creds(), "fabricNode")
        self.assertEqual(rows, [{"id": "0"}])

    async def test_query_class_rejects_bad_class_names(self) -> None:
        for name in ("", "fabric Node", "a/b", "a.json?x=1", "../x", "1abc"):
            with self.assertRaises(AciValidationError, msg=name):
                await self.service.query_class(_creds(), name)
        self.assertEqual(self.apic.requests, [])

    async def test_query_class_rejects_non_json_shape(self) -> None:
        self.apic.api_responses = [httpx.Response(200, json={"unexpected": True})]
        with self.assertRaises(AciAPIError) as ctx:
            await self.service.query_class(_creds(), "fabricNode")
        self.assertEqual(ctx.exception.code, "invalid_response")

    # --- error mapping -----------------------------------------------------

    async def test_404_maps_to_not_found(self) -> None:
        self.apic.api_responses = [httpx.Response(404)]
        with self.assertRaises(AciNotFoundError):
            await self.service.get(_creds(), "/api/class/a.json")

    async def test_400_carries_the_apic_error_text_capped(self) -> None:
        text = "x" * 1000
        self.apic.api_responses = [
            httpx.Response(400, json={"imdata": [{"error": {"attributes": {"text": text}}}]})
        ]
        with self.assertRaises(AciValidationError) as ctx:
            await self.service.get(_creds(), "/api/class/a.json")
        self.assertLessEqual(len(str(ctx.exception)), 300)
        self.assertIn("xxx", str(ctx.exception))

    async def test_400_without_usable_body_uses_generic_text(self) -> None:
        self.apic.api_responses = [httpx.Response(400, text="not json")]
        with self.assertRaises(AciValidationError) as ctx:
            await self.service.get(_creds(), "/api/class/a.json")
        self.assertIn("400", str(ctx.exception))

    async def test_500_message_has_no_body_text(self) -> None:
        self.apic.api_responses = [httpx.Response(500, text="secret-detail")]
        with self.assertRaises(AciAPIError) as ctx:
            await self.service.get(_creds(), "/api/class/a.json")
        self.assertNotIn("secret-detail", str(ctx.exception))
        self.assertEqual(ctx.exception.http_status, 500)

    async def test_non_json_success_body_is_invalid_response(self) -> None:
        self.apic.api_responses = [httpx.Response(200, text="<html>")]
        with self.assertRaises(AciAPIError) as ctx:
            await self.service.get(_creds(), "/api/class/a.json")
        self.assertEqual(ctx.exception.code, "invalid_response")

    async def test_429_is_retried_with_retry_after_then_succeeds(self) -> None:
        self.apic.api_responses = [
            httpx.Response(429, headers={"Retry-After": "3"}),
            httpx.Response(200, json={"totalCount": "0", "imdata": []}),
        ]
        await self.service.get(_creds(), "/api/class/a.json")
        self.assertEqual(self.sleeps, [3.0])

    async def test_429_exhausts_retries(self) -> None:
        self.apic.api_responses = [httpx.Response(429)] * 4
        with self.assertRaises(AciRateLimitError):
            await self.service.get(_creds(), "/api/class/a.json")
        self.assertEqual(self.sleeps, [1.0, 2.0, 4.0])

    async def test_timeout_maps_to_api_error(self) -> None:
        def boom(request: httpx.Request) -> httpx.Response:
            if request.url.path == LOGIN_PATH:
                return httpx.Response(200, json=_login_body())
            raise httpx.ReadTimeout("slow", request=request)

        service = AciService()
        http = httpx.AsyncClient(transport=httpx.MockTransport(boom))
        service._client_verify = service._client_no_verify = http
        try:
            with self.assertRaises(AciAPIError) as ctx:
                await service.get(_creds(), "/api/class/a.json")
        finally:
            await http.aclose()
        self.assertEqual(ctx.exception.code, "timeout")

    async def test_failure_classification_never_copies_text(self) -> None:
        self.apic.login_status = 401
        with self.assertRaises(AciAuthError) as ctx:
            await self.service.get(_creds(), "/api/class/a.json")
        failure = ctx.exception.failure
        self.assertEqual(failure.kind, "auth_failed")
        self.assertEqual(failure.hint, "check_credentials")
        self.assertFalse(failure.retryable)


if __name__ == "__main__":
    unittest.main()

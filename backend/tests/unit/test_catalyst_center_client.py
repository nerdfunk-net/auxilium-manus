"""Tests for the Catalyst Center HTTP client: token auth, 401 retry, error mapping."""

from __future__ import annotations

import base64
import unittest

import httpx

from services.catalyst_center.client import CatalystCenterService
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterAuthError,
    CatalystCenterNotFoundError,
    CatalystCenterRateLimitError,
    CatalystCenterValidationError,
)
from services.catalyst_center.credentials import CatalystCenterCredentials

AUTH_PATH = "/dna/system/api/v1/auth/token"


def _creds(**overrides) -> CatalystCenterCredentials:
    base = {"base_url": "https://10.10.20.85", "username": "admin", "password": "pw-1"}
    base.update(overrides)
    return CatalystCenterCredentials(**base)


class _Controller:
    """Scriptable fake controller recording every request."""

    def __init__(self, *, tokens=("tok-1", "tok-2", "tok-3")) -> None:
        self.requests: list[httpx.Request] = []
        self._tokens = list(tokens)
        self.api_responses: list[httpx.Response] = []
        self.auth_status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == AUTH_PATH:
            if self.auth_status != 200:
                return httpx.Response(self.auth_status, json={"error": "secret-detail"})
            return httpx.Response(200, json={"Token": self._tokens.pop(0)})
        if self.api_responses:
            return self.api_responses.pop(0)
        return httpx.Response(200, json={"response": "ok"})

    @property
    def auth_calls(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == AUTH_PATH]

    @property
    def api_calls(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path != AUTH_PATH]


class CatalystCenterClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.controller = _Controller()
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self.controller.handler))
        self.service = CatalystCenterService()
        self.service._client_verify = self.http
        self.service._client_no_verify = self.http

    async def asyncTearDown(self) -> None:
        await self.http.aclose()

    async def test_authenticates_with_basic_auth_then_sends_token(self) -> None:
        result = await self.service.request(_creds(), "GET", "/dna/intent/api/v1/network-device")
        self.assertEqual(result, {"response": "ok"})

        auth = self.controller.auth_calls[0]
        self.assertEqual(auth.method, "POST")
        expected = base64.b64encode(b"admin:pw-1").decode()
        self.assertEqual(auth.headers["authorization"], f"Basic {expected}")
        self.assertEqual(self.controller.api_calls[0].headers["x-auth-token"], "tok-1")

    async def test_reuses_cached_token(self) -> None:
        await self.service.request(_creds(), "GET", "/a")
        await self.service.request(_creds(), "GET", "/b")
        self.assertEqual(len(self.controller.auth_calls), 1)
        self.assertEqual(len(self.controller.api_calls), 2)

    async def test_password_change_forces_new_token(self) -> None:
        await self.service.request(_creds(), "GET", "/a")
        await self.service.request(_creds(password="pw-2"), "GET", "/a")
        self.assertEqual(len(self.controller.auth_calls), 2)

    async def test_expired_token_is_refreshed(self) -> None:
        await self.service.request(_creds(), "GET", "/a")
        for key in list(self.service._tokens):
            token, _ = self.service._tokens[key]
            self.service._tokens[key] = (token, 0.0)
        await self.service.request(_creds(), "GET", "/a")
        self.assertEqual(len(self.controller.auth_calls), 2)

    async def test_401_triggers_single_reauth_and_retry(self) -> None:
        self.controller.api_responses = [httpx.Response(401), httpx.Response(200, json={"ok": 1})]
        result = await self.service.request(_creds(), "GET", "/a")
        self.assertEqual(result, {"ok": 1})
        self.assertEqual(len(self.controller.auth_calls), 2)
        self.assertEqual(self.controller.api_calls[1].headers["x-auth-token"], "tok-2")

    async def test_second_401_raises_auth_error(self) -> None:
        self.controller.api_responses = [httpx.Response(401), httpx.Response(401)]
        with self.assertRaises(CatalystCenterAuthError):
            await self.service.request(_creds(), "GET", "/a")
        self.assertEqual(len(self.controller.api_calls), 2)

    async def test_auth_failure_raises_without_leaking_body(self) -> None:
        self.controller.auth_status = 401
        with self.assertRaises(CatalystCenterAuthError) as ctx:
            await self.service.request(_creds(), "GET", "/a")
        self.assertNotIn("secret-detail", str(ctx.exception))

    async def test_403_raises_auth_error(self) -> None:
        self.controller.api_responses = [httpx.Response(403)]
        with self.assertRaises(CatalystCenterAuthError):
            await self.service.request(_creds(), "GET", "/a")

    async def test_404_maps_to_not_found(self) -> None:
        self.controller.api_responses = [httpx.Response(404)]
        with self.assertRaises(CatalystCenterNotFoundError):
            await self.service.request(_creds(), "GET", "/dna/intent/api/v1/network-device/x")

    async def test_400_maps_to_validation_with_title(self) -> None:
        self.controller.api_responses = [
            httpx.Response(400, json={"response": {"message": "bad hostname", "detail": "x"}})
        ]
        with self.assertRaises(CatalystCenterValidationError) as ctx:
            await self.service.request(_creds(), "GET", "/a")
        self.assertIn("bad hostname", str(ctx.exception))

    async def test_5xx_maps_to_api_error_without_body(self) -> None:
        self.controller.api_responses = [httpx.Response(500, text="Traceback secret")]
        with self.assertRaises(CatalystCenterAPIError) as ctx:
            await self.service.request(_creds(), "GET", "/a")
        self.assertNotIn("Traceback", str(ctx.exception))
        self.assertIn("500", str(ctx.exception))

    async def test_timeout_maps_to_api_error(self) -> None:
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        self.service._client_verify = httpx.AsyncClient(transport=httpx.MockTransport(boom))
        with self.assertRaises(CatalystCenterAPIError) as ctx:
            await self.service.request(_creds(), "GET", "/a")
        self.assertIn("timed out", str(ctx.exception))

    async def test_transport_error_maps_to_api_error(self) -> None:
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        self.service._client_verify = httpx.AsyncClient(transport=httpx.MockTransport(boom))
        with self.assertRaises(CatalystCenterAPIError):
            await self.service.request(_creds(), "GET", "/a")

    async def test_missing_credentials_rejected_before_network(self) -> None:
        with self.assertRaises(CatalystCenterValidationError):
            await self.service.request(_creds(password=""), "GET", "/a")
        self.assertEqual(self.controller.requests, [])

    async def test_empty_body_returns_empty_dict(self) -> None:
        self.controller.api_responses = [httpx.Response(200)]
        self.assertEqual(await self.service.request(_creds(), "GET", "/a"), {})

    async def test_passes_params_and_json(self) -> None:
        await self.service.request(
            _creds(), "POST", "/a", params={"limit": 5}, json={"commands": ["show ver"]}
        )
        call = self.controller.api_calls[0]
        self.assertEqual(call.url.params["limit"], "5")
        self.assertEqual(call.read(), b'{"commands":["show ver"]}')

    async def test_verify_ssl_selects_pool(self) -> None:
        verify_calls: list[str] = []
        other = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: (
                    verify_calls.append(r.url.path) or httpx.Response(200, json={"Token": "t"})
                    if r.url.path == AUTH_PATH
                    else httpx.Response(200, json={})
                )
            )
        )
        self.service._client_no_verify = other
        await self.service.request(_creds(verify_ssl=False), "GET", "/a")
        self.assertEqual(self.controller.requests, [])
        self.assertIn(AUTH_PATH, verify_calls)
        await other.aclose()


class CatalystCenterClientEdgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.controller = _Controller()
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self.controller.handler))
        self.service = CatalystCenterService()
        self.service._client_verify = self.http
        self.service._client_no_verify = self.http

    async def asyncTearDown(self) -> None:
        await self.http.aclose()

    async def test_startup_creates_and_shutdown_closes_pools(self) -> None:
        service = CatalystCenterService()
        await service.startup()
        self.assertIsNotNone(service._client_verify)
        self.assertIsNotNone(service._client_no_verify)
        service._tokens[("u", "n", "d")] = ("t", 1.0)
        await service.shutdown()
        self.assertIsNone(service._client_verify)
        self.assertIsNone(service._client_no_verify)
        self.assertEqual(service._tokens, {})

    async def test_metadata_address_is_rejected_before_network(self) -> None:
        with self.assertRaises(CatalystCenterValidationError):
            await self.service.request(_creds(base_url="https://169.254.169.254"), "GET", "/a")
        self.assertEqual(self.controller.requests, [])

    async def test_token_endpoint_server_error_raises_api_error(self) -> None:
        self.controller.auth_status = 500
        with self.assertRaises(CatalystCenterAPIError) as ctx:
            await self.service.request(_creds(), "GET", "/a")
        self.assertIn("500", str(ctx.exception))

    async def test_token_response_without_token_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"nope": 1})

        self.service._client_verify = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with self.assertRaises(CatalystCenterAPIError):
            await self.service.request(_creds(), "GET", "/a")

    async def test_token_response_not_json_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>")

        self.service._client_verify = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with self.assertRaises(CatalystCenterAPIError):
            await self.service.request(_creds(), "GET", "/a")

    async def test_non_json_success_body_raises(self) -> None:
        self.controller.api_responses = [httpx.Response(200, text="plain text")]
        with self.assertRaises(CatalystCenterAPIError):
            await self.service.request(_creds(), "GET", "/a")

    async def test_400_without_message_uses_generic_text(self) -> None:
        self.controller.api_responses = [httpx.Response(400, text="not json")]
        with self.assertRaises(CatalystCenterValidationError) as ctx:
            await self.service.request(_creds(), "GET", "/a")
        self.assertIn("400", str(ctx.exception))


class CatalystCenterRateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.controller = _Controller()
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self.controller.handler))
        self.service = CatalystCenterService()
        self.service._client_verify = self.http
        self.service._client_no_verify = self.http
        self.sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            self.sleeps.append(seconds)

        self.service._sleep = fake_sleep

    async def asyncTearDown(self) -> None:
        await self.http.aclose()

    async def test_retries_after_429_honouring_retry_after(self) -> None:
        self.controller.api_responses = [
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={"ok": 1}),
        ]
        result = await self.service.request(_creds(), "GET", "/a")
        self.assertEqual(result, {"ok": 1})
        self.assertEqual(self.sleeps, [7.0])
        self.assertEqual(len(self.controller.api_calls), 2)

    async def test_retry_after_is_capped(self) -> None:
        self.controller.api_responses = [
            httpx.Response(429, headers={"Retry-After": "9999"}),
            httpx.Response(200, json={}),
        ]
        await self.service.request(_creds(), "GET", "/a")
        self.assertEqual(self.sleeps, [30.0])

    async def test_missing_or_invalid_retry_after_uses_backoff(self) -> None:
        self.controller.api_responses = [
            httpx.Response(429),
            httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
            httpx.Response(429, headers={"Retry-After": "-5"}),
            httpx.Response(200, json={}),
        ]
        await self.service.request(_creds(), "GET", "/a")
        self.assertEqual(self.sleeps, [1.0, 2.0, 4.0])

    async def test_gives_up_after_bounded_retries(self) -> None:
        self.controller.api_responses = [httpx.Response(429)] * 10
        with self.assertRaises(CatalystCenterRateLimitError):
            await self.service.request(_creds(), "GET", "/a")
        self.assertEqual(len(self.controller.api_calls), 4)  # 1 try + 3 retries
        self.assertEqual(len(self.sleeps), 3)

    async def test_rate_limit_error_is_an_api_error(self) -> None:
        self.assertTrue(issubclass(CatalystCenterRateLimitError, CatalystCenterAPIError))

    async def test_429_on_token_endpoint_is_retried(self) -> None:
        calls = {"auth": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == AUTH_PATH:
                calls["auth"] += 1
                if calls["auth"] == 1:
                    return httpx.Response(429, headers={"Retry-After": "2"})
                return httpx.Response(200, json={"Token": "t"})
            return httpx.Response(200, json={"ok": 1})

        self.service._client_verify = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.assertEqual(await self.service.request(_creds(), "GET", "/a"), {"ok": 1})
        self.assertEqual(calls["auth"], 2)
        self.assertEqual(self.sleeps, [2.0])

    async def test_non_429_errors_are_not_retried(self) -> None:
        self.controller.api_responses = [httpx.Response(500)]
        with self.assertRaises(CatalystCenterAPIError):
            await self.service.request(_creds(), "GET", "/a")
        self.assertEqual(self.sleeps, [])
        self.assertEqual(len(self.controller.api_calls), 1)

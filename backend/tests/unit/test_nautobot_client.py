"""Unit tests for services/nautobot/client.py (NautobotService).

The outbound-URL validator is patched to a fixed base and the httpx client
pools are replaced with MagicMocks — no DNS, no sockets.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from core.safe_urls import UnsafeURLError
from services.nautobot.client import NautobotService
from services.nautobot.common.exceptions import (
    NautobotAPIError,
    NautobotNotFoundError,
    NautobotValidationError,
)
from services.nautobot.credentials import NautobotCredentials

_CREDS = NautobotCredentials(url="http://nautobot.test", token="tok", timeout=5.0)
_NO_URL = NautobotCredentials(url="", token="")


def _response(status_code: int, json_body: dict | None = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body if json_body is not None else {}
    resp.text = text
    return resp


def _service_with_mock_client(response: MagicMock | Exception) -> NautobotService:
    svc = NautobotService()
    client = MagicMock()
    if isinstance(response, Exception):
        client.post = AsyncMock(side_effect=response)
        client.request = AsyncMock(side_effect=response)
    else:
        client.post = AsyncMock(return_value=response)
        client.request = AsyncMock(return_value=response)
    svc._client_verify = client
    svc._client_no_verify = client
    return svc


class _PatchValidator(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = patch(
            "services.nautobot.client.validate_outbound_http_url_async",
            return_value="http://nautobot.test",
        )
        self.addCleanup(patcher.stop)
        self.validator = patcher.start()


class GraphqlQueryTests(_PatchValidator):
    async def test_missing_credentials_raises_validation_error(self) -> None:
        with self.assertRaises(NautobotValidationError):
            await NautobotService().graphql_query("q", None, _NO_URL)

    async def test_unsafe_url_raises_validation_error(self) -> None:
        self.validator.side_effect = UnsafeURLError("blocked")
        with self.assertRaises(NautobotValidationError):
            await NautobotService().graphql_query("q", None, _CREDS)

    async def test_success_returns_parsed_json(self) -> None:
        svc = _service_with_mock_client(_response(200, {"data": {"devices": []}}))
        result = await svc.graphql_query("q", {"v": 1}, _CREDS)
        self.assertEqual(result, {"data": {"devices": []}})

    async def test_non_200_raises_api_error(self) -> None:
        svc = _service_with_mock_client(_response(500, text="server boom"))
        with self.assertRaises(NautobotAPIError):
            await svc.graphql_query("q", None, _CREDS)

    async def test_timeout_raises_api_error(self) -> None:
        svc = _service_with_mock_client(httpx.TimeoutException("slow"))
        with self.assertRaises(NautobotAPIError) as ctx:
            await svc.graphql_query("q", None, _CREDS)
        self.assertIn("timed out", str(ctx.exception))

    async def test_generic_error_wrapped_as_api_error(self) -> None:
        svc = _service_with_mock_client(RuntimeError("weird"))
        with self.assertRaises(NautobotAPIError):
            await svc.graphql_query("q", None, _CREDS)


class RestRequestTests(_PatchValidator):
    async def test_missing_credentials_raises_validation_error(self) -> None:
        with self.assertRaises(NautobotValidationError):
            await NautobotService().rest_request("status/", _NO_URL)

    async def test_200_returns_json(self) -> None:
        svc = _service_with_mock_client(_response(200, {"count": 3}))
        self.assertEqual(await svc.rest_request("dcim/devices/", _CREDS), {"count": 3})

    async def test_201_returns_json(self) -> None:
        svc = _service_with_mock_client(_response(201, {"id": "new"}))
        self.assertEqual(await svc.rest_request("x/", _CREDS, method="POST"), {"id": "new"})

    async def test_204_returns_success_envelope(self) -> None:
        svc = _service_with_mock_client(_response(204))
        result = await svc.rest_request("x/", _CREDS, method="DELETE")
        self.assertEqual(result["status"], "success")

    async def test_404_raises_not_found(self) -> None:
        svc = _service_with_mock_client(_response(404, text="missing"))
        with self.assertRaises(NautobotNotFoundError):
            await svc.rest_request("x/", _CREDS)

    async def test_500_raises_api_error(self) -> None:
        svc = _service_with_mock_client(_response(500, text="boom"))
        with self.assertRaises(NautobotAPIError):
            await svc.rest_request("x/", _CREDS)

    async def test_timeout_raises_api_error(self) -> None:
        svc = _service_with_mock_client(httpx.TimeoutException("slow"))
        with self.assertRaises(NautobotAPIError):
            await svc.rest_request("x/", _CREDS)

    async def test_test_connection_delegates_to_status_endpoint(self) -> None:
        svc = _service_with_mock_client(_response(200, {"nautobot-version": "2.0"}))
        result = await svc.test_connection(_CREDS)
        self.assertEqual(result, {"nautobot-version": "2.0"})
        called_url = svc._client_verify.request.await_args.args[1]
        self.assertTrue(called_url.endswith("/api/status/"))

    async def test_falls_back_to_ephemeral_client_when_pool_absent(self) -> None:
        svc = NautobotService()  # startup() never called -> pools are None
        fake_client = MagicMock()
        fake_client.request = AsyncMock(return_value=_response(200, {"ok": True}))
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=fake_client)
        cm.__aexit__ = AsyncMock(return_value=False)
        with patch("services.nautobot.client.httpx.AsyncClient", return_value=cm):
            result = await svc.rest_request("status/", _CREDS)
        self.assertEqual(result, {"ok": True})


class ClientLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_and_shutdown_manage_pools(self) -> None:
        svc = NautobotService()
        self.assertIsNone(svc._client_for(True))
        await svc.startup()
        self.assertIsNotNone(svc._client_for(True))
        self.assertIsNotNone(svc._client_for(False))
        await svc.shutdown()
        self.assertIsNone(svc._client_for(True))
        self.assertIsNone(svc._client_for(False))

    async def test_client_for_selects_verify_pool(self) -> None:
        svc = NautobotService()
        svc._client_verify = "VERIFY"
        svc._client_no_verify = "NO_VERIFY"
        self.assertEqual(svc._client_for(True), "VERIFY")
        self.assertEqual(svc._client_for(False), "NO_VERIFY")


if __name__ == "__main__":
    unittest.main()

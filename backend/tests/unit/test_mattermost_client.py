"""Tests for MattermostService.check_connection()."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

import httpx

from services.mattermost.client import MattermostService
from services.mattermost.common.exceptions import MattermostAPIError
from services.mattermost.credentials import MattermostCredentials


def _credentials(**overrides) -> MattermostCredentials:
    base = {"base_url": "http://localhost:8065", "token": "bot-token"}
    base.update(overrides)
    return MattermostCredentials(**base)


class MattermostServiceCheckConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service = MattermostService()
        self.mock_client = AsyncMock()
        self.service._client_verify = self.mock_client
        self.service._client_no_verify = self.mock_client

    async def test_check_connection_returns_json_body(self) -> None:
        self.mock_client.request.return_value = httpx.Response(
            200, json={"id": "abc123", "username": "workflow-bot"}
        )
        result = await self.service.check_connection(_credentials())
        self.assertEqual(result["username"], "workflow-bot")

        call = self.mock_client.request.call_args
        self.assertEqual(call.args[0], "GET")
        self.assertTrue(call.args[1].endswith("/api/v4/users/me"))
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer bot-token")

    async def test_check_connection_401_raises_api_error(self) -> None:
        self.mock_client.request.return_value = httpx.Response(401)
        with self.assertRaises(MattermostAPIError):
            await self.service.check_connection(_credentials())

    async def test_check_connection_500_raises_api_error(self) -> None:
        self.mock_client.request.return_value = httpx.Response(500)
        with self.assertRaises(MattermostAPIError):
            await self.service.check_connection(_credentials())

    async def test_check_connection_timeout_raises_api_error(self) -> None:
        self.mock_client.request.side_effect = httpx.TimeoutException("timed out")
        with self.assertRaises(MattermostAPIError):
            await self.service.check_connection(_credentials())

    async def test_check_connection_redirect_raises_api_error_not_crash(self) -> None:
        self.mock_client.request.return_value = httpx.Response(
            301,
            headers={"location": "https://mattermost.example.com/api/v4/users/me"},
        )
        with self.assertRaises(MattermostAPIError) as ctx:
            await self.service.check_connection(_credentials())
        self.assertIn("redirected", str(ctx.exception))

    async def test_check_connection_non_json_body_raises_api_error_not_crash(self) -> None:
        self.mock_client.request.return_value = httpx.Response(
            200, content=b"<html>not json</html>"
        )
        with self.assertRaises(MattermostAPIError) as ctx:
            await self.service.check_connection(_credentials())
        self.assertIn("non-JSON", str(ctx.exception))


class MattermostServiceGetChannelByNameTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service = MattermostService()
        self.mock_client = AsyncMock()
        self.service._client_verify = self.mock_client
        self.service._client_no_verify = self.mock_client

    async def test_get_channel_by_name_returns_json_body(self) -> None:
        self.mock_client.request.return_value = httpx.Response(
            200, json={"id": "chan123", "name": "alerts"}
        )
        result = await self.service.get_channel_by_name(_credentials(), "networking", "alerts")
        self.assertEqual(result["id"], "chan123")

        call = self.mock_client.request.call_args
        self.assertEqual(call.args[0], "GET")
        self.assertTrue(
            call.args[1].endswith("/api/v4/teams/name/networking/channels/name/alerts")
        )
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer bot-token")

    async def test_get_channel_by_name_404_raises_api_error_with_names(self) -> None:
        self.mock_client.request.return_value = httpx.Response(404)
        with self.assertRaises(MattermostAPIError) as ctx:
            await self.service.get_channel_by_name(_credentials(), "networking", "alerts")
        self.assertIn("networking", str(ctx.exception))
        self.assertIn("alerts", str(ctx.exception))

    async def test_get_channel_by_name_401_raises_api_error(self) -> None:
        self.mock_client.request.return_value = httpx.Response(401)
        with self.assertRaises(MattermostAPIError):
            await self.service.get_channel_by_name(_credentials(), "networking", "alerts")

    async def test_get_channel_by_name_timeout_raises_api_error(self) -> None:
        self.mock_client.request.side_effect = httpx.TimeoutException("timed out")
        with self.assertRaises(MattermostAPIError):
            await self.service.get_channel_by_name(_credentials(), "networking", "alerts")


class MattermostServiceCreatePostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service = MattermostService()
        self.mock_client = AsyncMock()
        self.service._client_verify = self.mock_client
        self.service._client_no_verify = self.mock_client

    async def test_create_post_returns_json_body(self) -> None:
        self.mock_client.request.return_value = httpx.Response(201, json={"id": "post123"})
        result = await self.service.create_post(_credentials(), "chan123", "hello")
        self.assertEqual(result["id"], "post123")

        call = self.mock_client.request.call_args
        self.assertEqual(call.args[0], "POST")
        self.assertTrue(call.args[1].endswith("/api/v4/posts"))
        self.assertEqual(
            call.kwargs["json"], {"channel_id": "chan123", "message": "hello"}
        )

    async def test_create_post_500_raises_api_error(self) -> None:
        self.mock_client.request.return_value = httpx.Response(500)
        with self.assertRaises(MattermostAPIError):
            await self.service.create_post(_credentials(), "chan123", "hello")

    async def test_create_post_timeout_raises_api_error(self) -> None:
        self.mock_client.request.side_effect = httpx.TimeoutException("timed out")
        with self.assertRaises(MattermostAPIError):
            await self.service.create_post(_credentials(), "chan123", "hello")


if __name__ == "__main__":
    unittest.main()

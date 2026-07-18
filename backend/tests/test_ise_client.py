"""Tests for the Cisco ISE ERS API client's status-code handling."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

import httpx

from services.ise.client import ISEService
from services.ise.common.exceptions import (
    ISEAPIError,
    ISENotFoundError,
    ISEValidationError,
)
from services.ise.credentials import ISECredentials


def _credentials(**overrides) -> ISECredentials:
    base = {
        "base_url": "https://10.10.20.77",
        "username": "admin",
        "password": "C1sco12345!",
    }
    base.update(overrides)
    return ISECredentials(**base)


class ISEClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service = ISEService()
        self.mock_client = AsyncMock()
        self.service._client_verify = self.mock_client
        self.service._client_no_verify = self.mock_client

    async def test_get_returns_json_body(self) -> None:
        self.mock_client.request.return_value = httpx.Response(
            200, json={"NetworkDevice": {"id": "abc", "name": "router1"}}
        )
        result = await self.service.ers_request("networkdevice/abc", _credentials())
        self.assertEqual(result["NetworkDevice"]["name"], "router1")

    async def test_create_parses_id_from_location_header(self) -> None:
        self.mock_client.request.return_value = httpx.Response(
            201,
            headers={
                "Location": (
                    "https://10.10.20.77/ers/config/networkdevice/"
                    "89bf4070-8290-11f1-b5fd-3eac1c258930"
                )
            },
        )
        result = await self.service.ers_request(
            "networkdevice",
            _credentials(),
            method="POST",
            data={"NetworkDevice": {"name": "router1"}},
        )
        self.assertEqual(result["id"], "89bf4070-8290-11f1-b5fd-3eac1c258930")

    async def test_delete_returns_success_on_204(self) -> None:
        self.mock_client.request.return_value = httpx.Response(204)
        result = await self.service.ers_request(
            "networkdevice/abc", _credentials(), method="DELETE"
        )
        self.assertEqual(result["status"], "success")

    async def test_404_raises_not_found(self) -> None:
        self.mock_client.request.return_value = httpx.Response(404)
        with self.assertRaises(ISENotFoundError):
            await self.service.ers_request("networkdevice/missing", _credentials())

    async def test_400_raises_validation_error_with_ise_message(self) -> None:
        self.mock_client.request.return_value = httpx.Response(
            400,
            json={
                "ERSResponse": {
                    "messages": [
                        {
                            "title": "Validation Error - Mandatory fields missing: [Name]",
                            "type": "ERROR",
                        }
                    ]
                }
            },
        )
        with self.assertRaises(ISEValidationError) as ctx:
            await self.service.ers_request(
                "networkdevice", _credentials(), method="POST", data={"NetworkDevice": {}}
            )
        self.assertIn("Mandatory fields missing", str(ctx.exception))

    async def test_500_raises_api_error(self) -> None:
        self.mock_client.request.return_value = httpx.Response(500, text="boom")
        with self.assertRaises(ISEAPIError):
            await self.service.ers_request("networkdevice", _credentials())

    async def test_timeout_raises_api_error(self) -> None:
        self.mock_client.request.side_effect = httpx.TimeoutException("timed out")
        with self.assertRaises(ISEAPIError):
            await self.service.ers_request("networkdevice", _credentials())

    async def test_missing_credentials_raise_validation_error(self) -> None:
        with self.assertRaises(ISEValidationError):
            await self.service.ers_request(
                "networkdevice", _credentials(password="")
            )

    async def test_error_message_never_contains_password(self) -> None:
        self.mock_client.request.return_value = httpx.Response(500, text="boom")
        try:
            await self.service.ers_request("networkdevice", _credentials())
        except ISEAPIError as exc:
            self.assertNotIn("C1sco12345!", str(exc))
        else:
            self.fail("expected ISEAPIError")

    async def test_uses_verify_ssl_client(self) -> None:
        verify_client = AsyncMock()
        no_verify_client = AsyncMock()
        self.service._client_verify = verify_client
        self.service._client_no_verify = no_verify_client
        verify_client.request.return_value = httpx.Response(200, json={})
        no_verify_client.request.return_value = httpx.Response(200, json={})

        await self.service.ers_request(
            "networkdevice", _credentials(verify_ssl=False)
        )
        no_verify_client.request.assert_called_once()
        verify_client.request.assert_not_called()

        await self.service.ers_request(
            "networkdevice", _credentials(verify_ssl=True)
        )
        verify_client.request.assert_called_once()


if __name__ == "__main__":
    unittest.main()

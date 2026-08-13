"""Tests for PyATSShimService.diff()."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

import httpx

from services.pyats.client import PyATSShimService
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from services.pyats.credentials import PyATSCredentials


def _credentials(**overrides) -> PyATSCredentials:
    base = {"base_url": "http://10.0.0.5:8100", "token": "shim-token"}
    base.update(overrides)
    return PyATSCredentials(**base)


class PyATSShimServiceDiffTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service = PyATSShimService()
        self.mock_client = AsyncMock()
        self.service._client_verify = self.mock_client
        self.service._client_no_verify = self.mock_client

    async def test_diff_returns_json_body(self) -> None:
        self.mock_client.request.return_value = httpx.Response(
            200, json={"identical": True, "diff": ""}
        )
        result = await self.service.diff(
            _credentials(),
            snapshot_a={"info": {"a": 1}},
            snapshot_b={"info": {"a": 1}},
        )
        self.assertEqual(result, {"identical": True, "diff": ""})

        call = self.mock_client.request.call_args
        self.assertEqual(call.args[0], "POST")
        self.assertTrue(call.args[1].endswith("/v1/diff"))
        self.assertEqual(
            call.kwargs["json"],
            {"snapshot_a": {"info": {"a": 1}}, "snapshot_b": {"info": {"a": 1}}},
        )
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer shim-token")

    async def test_diff_400_raises_validation_error(self) -> None:
        self.mock_client.request.return_value = httpx.Response(
            400, json={"detail": "Genie diff failed: incompatible shapes"}
        )
        with self.assertRaises(PyATSValidationError) as ctx:
            await self.service.diff(
                _credentials(), snapshot_a={"info": {}}, snapshot_b={"info": {}}
            )
        self.assertIn("incompatible shapes", str(ctx.exception))

    async def test_diff_500_raises_api_error(self) -> None:
        self.mock_client.request.return_value = httpx.Response(500)
        with self.assertRaises(PyATSAPIError):
            await self.service.diff(
                _credentials(), snapshot_a={"info": {}}, snapshot_b={"info": {}}
            )

    async def test_diff_timeout_raises_api_error(self) -> None:
        self.mock_client.request.side_effect = httpx.TimeoutException("timed out")
        with self.assertRaises(PyATSAPIError):
            await self.service.diff(
                _credentials(), snapshot_a={"info": {}}, snapshot_b={"info": {}}
            )


if __name__ == "__main__":
    unittest.main()

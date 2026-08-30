"""Unit tests for services/nautobot/devices/types.py validators and
services/nautobot/credentials_bound_client.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from services.nautobot.credentials import NautobotCredentials
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.devices.types import DeviceIdentifier, InterfaceSpec


class DeviceIdentifierValidationTests(unittest.TestCase):
    def test_blank_strings_are_coerced_to_none_and_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DeviceIdentifier(id="   ", name="", ip_address=None)

    def test_requires_at_least_one_identifier(self) -> None:
        with pytest.raises(ValidationError):
            DeviceIdentifier()

    def test_accepts_single_identifier(self) -> None:
        self.assertEqual(DeviceIdentifier(name="r1").name, "r1")


class InterfaceSpecValidationTests(unittest.TestCase):
    def test_namespace_required_when_ip_present(self) -> None:
        with pytest.raises(ValidationError):
            InterfaceSpec(name="Gi0/0", type="virtual", ip_address="10.0.0.1/24", namespace=None)

    def test_ip_with_namespace_is_valid(self) -> None:
        spec = InterfaceSpec(
            name="Gi0/0", type="virtual", ip_address="10.0.0.1/24", namespace="Global"
        )
        self.assertEqual(spec.namespace, "Global")


class CredentialsBoundClientTests(unittest.IsolatedAsyncioTestCase):
    def _client(self) -> tuple[CredentialsBoundNautobotClient, MagicMock, NautobotCredentials]:
        service = MagicMock()
        service.graphql_query = AsyncMock(return_value={"data": {}})
        service.rest_request = AsyncMock(return_value={"count": 0})
        creds = NautobotCredentials(url="http://nb.test", token="tok")
        return CredentialsBoundNautobotClient(service, creds), service, creds

    async def test_graphql_query_injects_credentials(self) -> None:
        client, service, creds = self._client()
        await client.graphql_query("query { x }", {"v": 1})
        service.graphql_query.assert_awaited_once_with("query { x }", {"v": 1}, creds)

    async def test_rest_request_injects_credentials_and_options(self) -> None:
        client, service, creds = self._client()
        await client.rest_request("dcim/devices/", method="POST", data={"name": "r1"})
        service.rest_request.assert_awaited_once_with(
            "dcim/devices/", creds, method="POST", data={"name": "r1"}
        )


if __name__ == "__main__":
    unittest.main()

"""Tests for services/sources/nautobot/metadata_service.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.credentials import NautobotCredentials
from services.sources.nautobot.metadata_service import NautobotSourceMetadataService

_CREDS = NautobotCredentials(url="http://nb.test", token="tok")


def _service(rest_side_effect=None, rest_return=None) -> NautobotSourceMetadataService:
    nautobot = MagicMock()
    if rest_side_effect is not None:
        nautobot.rest_request = AsyncMock(side_effect=rest_side_effect)
    else:
        nautobot.rest_request = AsyncMock(return_value=rest_return or {})
    return NautobotSourceMetadataService(nautobot, _CREDS)


class GetCustomFieldsTests(unittest.IsolatedAsyncioTestCase):
    async def test_transforms_and_caches(self) -> None:
        svc = _service(
            rest_return={
                "results": [
                    {
                        "key": "site_code",
                        "label": {"display": "Site Code"},
                        "type": {"value": "select"},
                    },
                    {"name": "notes", "label": "Notes", "type": "text"},
                ]
            }
        )
        fields = await svc.get_custom_fields()
        self.assertEqual(fields[0], {"name": "site_code", "label": "Site Code", "type": "select"})
        self.assertEqual(fields[1]["name"], "notes")
        # cached — a second call does not touch the client again
        svc._nautobot.rest_request.reset_mock()
        await svc.get_custom_fields()
        svc._nautobot.rest_request.assert_not_called()

    async def test_invalid_response_returns_empty(self) -> None:
        self.assertEqual(await _service(rest_return={"nope": 1}).get_custom_fields(), [])

    async def test_exception_returns_empty(self) -> None:
        self.assertEqual(
            await _service(rest_side_effect=RuntimeError("boom")).get_custom_fields(), []
        )


class GetFieldValuesTests(unittest.IsolatedAsyncioTestCase):
    async def test_name_field_returns_empty(self) -> None:
        self.assertEqual(await _service().get_field_values("name"), [])

    async def test_has_primary_returns_bool_choices(self) -> None:
        vals = await _service().get_field_values("has_primary")
        self.assertEqual({v["value"] for v in vals}, {"true", "false"})

    async def test_unknown_standard_field_returns_empty(self) -> None:
        self.assertEqual(await _service().get_field_values("mystery"), [])

    async def test_standard_field_maps_names(self) -> None:
        svc = _service(rest_return={"results": [{"name": "dc2"}, {"name": "dc1"}]})
        vals = await svc.get_field_values("location")
        self.assertEqual([v["value"] for v in vals], ["dc1", "dc2"])  # sorted by label

    async def test_device_type_field_includes_manufacturer(self) -> None:
        svc = _service(
            rest_return={
                "results": [{"model": "C9300", "manufacturer": {"name": "Cisco"}}]
            }
        )
        vals = await svc.get_field_values("device_type")
        self.assertEqual(vals[0], {"value": "C9300", "label": "Cisco C9300"})

    async def test_custom_fields_list(self) -> None:
        svc = _service(
            rest_return={"results": [{"key": "site", "label": "Site", "type": "text"}]}
        )
        vals = await svc.get_field_values("custom_fields")
        self.assertEqual(vals[0], {"value": "cf_site", "label": "Site"})

    async def test_cf_select_field_returns_choices(self) -> None:
        responses = [
            {"results": [{"key": "site", "label": "Site", "type": "select"}]},  # get_custom_fields
            {"results": [{"value": "NYC"}, {"value": "LON"}]},  # choices
        ]
        svc = _service(rest_side_effect=responses)
        vals = await svc.get_field_values("cf_site")
        self.assertEqual([v["value"] for v in vals], ["LON", "NYC"])

    async def test_cf_non_select_field_returns_empty(self) -> None:
        svc = _service(
            rest_return={"results": [{"key": "site", "label": "Site", "type": "text"}]}
        )
        self.assertEqual(await svc.get_field_values("cf_site"), [])

    async def test_get_field_values_swallows_errors(self) -> None:
        self.assertEqual(
            await _service(rest_side_effect=RuntimeError("boom")).get_field_values("location"), []
        )


if __name__ == "__main__":
    unittest.main()

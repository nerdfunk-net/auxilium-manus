"""Tests for services/sources/nautobot/export_service.py and connection.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.sources_nautobot import DeviceInfo, NautobotTestConnectionRequest
from services.sources.nautobot.connection import test_nautobot_connection as run_test_connection
from services.sources.nautobot.export_service import NautobotSourceExportService


def _dev(did: str) -> DeviceInfo:
    return DeviceInfo(id=did, name=did)


class AnalyzeDevicesTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_devices_returns_zeroed_structure(self) -> None:
        out = await NautobotSourceExportService(MagicMock()).analyze_devices([])
        self.assertEqual(out["device_count"], 0)
        self.assertEqual(out["custom_fields"], {})

    async def test_missing_query_service_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            await NautobotSourceExportService(None).analyze_devices([_dev("a")])

    async def test_aggregates_detail_fields(self) -> None:
        dqs = MagicMock()
        dqs.get_device_details = AsyncMock(
            side_effect=[
                {
                    "location": {"name": "dc1"},
                    "tags": [{"name": "prod"}, {"name": "edge"}],
                    "_custom_field_data": {"site": "NYC", "codes": ["x", "y"], "empty": None},
                    "status": {"name": "Active"},
                    "role": {"name": "leaf"},
                },
                RuntimeError("boom"),  # second device errors, is skipped
            ]
        )
        out = await NautobotSourceExportService(dqs).analyze_devices([_dev("a"), _dev("b")])
        self.assertEqual(out["locations"], ["dc1"])
        self.assertEqual(out["tags"], ["edge", "prod"])
        self.assertEqual(out["custom_fields"], {"site": ["NYC"], "codes": ["x", "y"]})
        self.assertEqual(out["statuses"], ["Active"])
        self.assertEqual(out["roles"], ["leaf"])
        self.assertEqual(out["device_count"], 2)


class TestConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_form_values_success_with_version(self) -> None:
        req = NautobotTestConnectionRequest(
            url="http://nb.test", credential_id=7, timeout=5, verify_ssl=True
        )
        with (
            patch("services.sources.nautobot.connection.service_factory") as sf,
            patch(
                "services.sources.nautobot.connection.resolve_global_secret",
                return_value=("nb", "tok"),
            ),
        ):
            sf.credentials_from_connection.return_value = "creds"
            sf.get_nautobot_app_service.return_value.test_connection = AsyncMock(
                return_value={"nautobot-version": "2.1.0"}
            )
            resp = await run_test_connection(req, MagicMock())
        self.assertTrue(resp.success)
        self.assertIn("2.1.0", resp.message)

    async def test_form_values_success_without_version(self) -> None:
        req = NautobotTestConnectionRequest(
            url="http://nb.test", credential_id=7, timeout=5, verify_ssl=False
        )
        with (
            patch("services.sources.nautobot.connection.service_factory") as sf,
            patch(
                "services.sources.nautobot.connection.resolve_global_secret",
                return_value=("nb", "tok"),
            ),
        ):
            sf.credentials_from_connection.return_value = "creds"
            sf.get_nautobot_app_service.return_value.test_connection = AsyncMock(return_value={})
            resp = await run_test_connection(req, MagicMock())
        self.assertEqual(resp.message, "Connection successful")

    async def test_saved_source_reads_settings_config(self) -> None:
        req = NautobotTestConnectionRequest(source_id="src-1", timeout=10)
        with (
            patch("services.sources.nautobot.connection.service_factory") as sf,
            patch("services.sources.nautobot.connection.SettingsService") as settings_cls,
        ):
            settings_cls.return_value.get_source_config.return_value = {
                "url": "http://saved", "token": "savedtok", "verify_ssl": False
            }
            sf.credentials_from_connection.return_value = "creds"
            sf.get_nautobot_app_service.return_value.test_connection = AsyncMock(
                return_value={"nautobot_version": "2.0"}
            )
            resp = await run_test_connection(req, MagicMock())
        settings_cls.return_value.get_source_config.assert_called_once_with("nautobot", "src-1")
        self.assertIn("2.0", resp.message)


if __name__ == "__main__":
    unittest.main()

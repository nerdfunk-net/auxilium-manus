"""Tests for scripts/ai_inventory_filter.py::count_inventory_devices — the
live device-count check behind AI_VOCABULARY.md's "fan-out threshold" rule.
External Nautobot/credential resolution is mocked at the module boundary
(each patched at its origin module, since count_inventory_devices imports
them locally); a real, live cross-check against the dev DB's actual LAB
inventory (3 devices, confirmed manually) is not included here since it makes
a real network call to Nautobot — see PROCESS.md for that manual verification.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.ai_inventory_filter import count_inventory_devices


class CountInventoryDevicesTests(unittest.TestCase):
    def test_returns_device_count_from_analysis(self) -> None:
        mock_source_service = MagicMock()
        mock_source_service.analyze_inventory = AsyncMock(return_value={"device_count": 7})
        mock_nautobot_service = MagicMock()
        mock_nautobot_service.startup = AsyncMock()
        mock_nautobot_service.shutdown = AsyncMock()

        with (
            patch(
                "workflow_steps.common.nautobot_source.resolve_nautobot_credentials",
                return_value=MagicMock(),
            ),
            patch(
                "services.nautobot.client.NautobotService", return_value=mock_nautobot_service
            ),
            patch("service_factory.set_nautobot_app_service"),
            patch(
                "service_factory.build_nautobot_source_service",
                return_value=mock_source_service,
            ),
        ):
            count = count_inventory_devices(
                MagicMock(), inventory_id=1, username="admin", nautobot_source_id="nautobot"
            )

        self.assertEqual(count, 7)
        mock_nautobot_service.startup.assert_awaited_once()
        mock_nautobot_service.shutdown.assert_awaited_once()

    def test_missing_device_count_key_defaults_to_zero(self) -> None:
        mock_source_service = MagicMock()
        mock_source_service.analyze_inventory = AsyncMock(return_value={})
        mock_nautobot_service = MagicMock()
        mock_nautobot_service.startup = AsyncMock()
        mock_nautobot_service.shutdown = AsyncMock()

        with (
            patch(
                "workflow_steps.common.nautobot_source.resolve_nautobot_credentials",
                return_value=MagicMock(),
            ),
            patch(
                "services.nautobot.client.NautobotService", return_value=mock_nautobot_service
            ),
            patch("service_factory.set_nautobot_app_service"),
            patch(
                "service_factory.build_nautobot_source_service",
                return_value=mock_source_service,
            ),
        ):
            count = count_inventory_devices(
                MagicMock(), inventory_id=1, username="admin", nautobot_source_id="nautobot"
            )

        self.assertEqual(count, 0)

    def test_shutdown_is_still_called_on_failure(self) -> None:
        mock_source_service = MagicMock()
        mock_source_service.analyze_inventory = AsyncMock(side_effect=RuntimeError("boom"))
        mock_nautobot_service = MagicMock()
        mock_nautobot_service.startup = AsyncMock()
        mock_nautobot_service.shutdown = AsyncMock()

        with (
            patch(
                "workflow_steps.common.nautobot_source.resolve_nautobot_credentials",
                return_value=MagicMock(),
            ),
            patch(
                "services.nautobot.client.NautobotService", return_value=mock_nautobot_service
            ),
            patch("service_factory.set_nautobot_app_service"),
            patch(
                "service_factory.build_nautobot_source_service",
                return_value=mock_source_service,
            ),
        ):
            with self.assertRaises(RuntimeError):
                count_inventory_devices(
                    MagicMock(), inventory_id=1, username="admin", nautobot_source_id="nautobot"
                )

        mock_nautobot_service.shutdown.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

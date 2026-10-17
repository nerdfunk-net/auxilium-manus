"""CF-07 fix 2: a prefix created concurrently by another worker is reused, not an error."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.nautobot.common.exceptions import NautobotAPIError
from services.nautobot.managers.prefix_manager import PrefixManager

_PATH = "services.nautobot.managers.prefix_manager"


class PrefixManagerRaceTests(unittest.IsolatedAsyncioTestCase):
    def _manager(self, post: AsyncMock) -> PrefixManager:
        manager = PrefixManager.__new__(PrefixManager)
        manager.nautobot = MagicMock()
        manager.nautobot.rest_request = post
        manager.network_resolver = MagicMock()
        manager.metadata_resolver = MagicMock()
        manager.metadata_resolver.resolve_status_id = AsyncMock(return_value="status-1")
        return manager

    async def test_duplicate_post_returns_the_concurrent_prefix(self) -> None:
        post = AsyncMock(side_effect=NautobotAPIError("prefix with this ... already exists"))
        manager = self._manager(post)
        with (
            patch(f"{_PATH}._resolve_namespace_ref", AsyncMock(return_value="ns-1")),
            patch(f"{_PATH}._find_prefix_id", AsyncMock(side_effect=[None, "prefix-from-peer"])),
            patch(f"{_PATH}._build_prefix_create_payload", AsyncMock(return_value={})),
        ):
            result = await manager.ensure_prefix_exists("10.0.0.0/24")
        self.assertEqual(result, "prefix-from-peer")

    async def test_other_api_errors_still_raise(self) -> None:
        post = AsyncMock(side_effect=NautobotAPIError("boom"))
        manager = self._manager(post)
        with (
            patch(f"{_PATH}._resolve_namespace_ref", AsyncMock(return_value="ns-1")),
            patch(f"{_PATH}._find_prefix_id", AsyncMock(return_value=None)),
            patch(f"{_PATH}._build_prefix_create_payload", AsyncMock(return_value={})),
        ):
            with self.assertRaises(NautobotAPIError):
                await manager.ensure_prefix_exists("10.0.0.0/24")


if __name__ == "__main__":
    unittest.main()

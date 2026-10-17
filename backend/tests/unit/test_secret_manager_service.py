"""SecretManagerService: validation before client lookup, blocking calls off-loop (SM5, SM8)."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.secret_manager.service import SecretManagerService


def _registry(client: MagicMock) -> MagicMock:
    registry = MagicMock()
    registry.get_or_create = AsyncMock(return_value=client)
    return registry


class SecretManagerServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_field_runs_in_thread(self) -> None:
        main_thread = threading.get_ident()
        seen: list[int] = []

        def get_field(path, field, version=None):
            seen.append(threading.get_ident())
            return "v"

        client = MagicMock()
        client.get_field = get_field
        with patch("service_factory.get_secret_manager_registry", return_value=_registry(client)):
            value = await SecretManagerService(MagicMock()).get_field(1, "a/b", "key")
        self.assertEqual(value, "v")
        self.assertNotEqual(seen[0], main_thread)

    async def test_set_field_runs_in_thread(self) -> None:
        main_thread = threading.get_ident()
        seen: list[int] = []

        def set_field(path, field, value):
            seen.append(threading.get_ident())
            return 2

        client = MagicMock()
        client.set_field = set_field
        with patch("service_factory.get_secret_manager_registry", return_value=_registry(client)):
            version = await SecretManagerService(MagicMock()).set_field(1, "a/b", "key", "x")
        self.assertEqual(version, 2)
        self.assertNotEqual(seen[0], main_thread)

    async def test_bad_path_raises_before_client_lookup(self) -> None:
        registry = _registry(MagicMock())
        service = SecretManagerService(MagicMock())
        with patch("service_factory.get_secret_manager_registry", return_value=registry):
            with self.assertRaises(ValueError):
                await service.get_field(1, "a/../b", "key")
            with self.assertRaises(ValueError):
                await service.set_field(1, "a/b", "../key", "x")
            with self.assertRaises(ValueError):
                await service.get_field_history(1, "a//b", "key")
        registry.get_or_create.assert_not_called()


if __name__ == "__main__":
    unittest.main()

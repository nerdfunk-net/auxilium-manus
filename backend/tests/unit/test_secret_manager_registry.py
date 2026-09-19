"""SecretManagerClientRegistry: lazy build, no caching on failed
ensure_started (SM1), invalidate, unknown backend."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.secret_manager.config import SecretManagerConnectionConfig
from services.secret_manager.exceptions import SecretManagerAuthError, SecretManagerConfigError
from services.secret_manager.registry import SecretManagerClientRegistry


def _cfg(backend: str = "openbao") -> SecretManagerConnectionConfig:
    return SecretManagerConnectionConfig(
        id=1, name="net", backend=backend, verify_ssl=True, backend_config={},
        auth_id="a", auth_secret="b",
    )


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_backend_is_config_error(self) -> None:
        with patch("services.secret_manager.registry.load_connection_config",
                   return_value=_cfg("nope")):
            with self.assertRaises(SecretManagerConfigError):
                await SecretManagerClientRegistry().get_or_create(1, MagicMock())

    async def test_failed_ensure_started_is_not_cached(self) -> None:
        client = MagicMock()
        client.ensure_started = AsyncMock(side_effect=SecretManagerAuthError("bad"))
        registry = SecretManagerClientRegistry()
        with (
            patch("services.secret_manager.registry.load_connection_config", return_value=_cfg()),
            patch("services.secret_manager.registry._build_client", return_value=client),
        ):
            with self.assertRaises(SecretManagerAuthError):
                await registry.get_or_create(1, MagicMock())
            self.assertEqual(registry._clients, {})

    async def test_second_call_reuses_client(self) -> None:
        client = MagicMock()
        client.ensure_started = AsyncMock()
        registry = SecretManagerClientRegistry()
        with (
            patch("services.secret_manager.registry.load_connection_config", return_value=_cfg()),
            patch("services.secret_manager.registry._build_client", return_value=client) as build,
        ):
            await registry.get_or_create(1, MagicMock())
            await registry.get_or_create(1, MagicMock())
        build.assert_called_once()

    async def test_invalidate_shuts_client_down(self) -> None:
        client = MagicMock()
        client.ensure_started = AsyncMock()
        client.shutdown = AsyncMock()
        registry = SecretManagerClientRegistry()
        with (
            patch("services.secret_manager.registry.load_connection_config", return_value=_cfg()),
            patch("services.secret_manager.registry._build_client", return_value=client),
        ):
            await registry.get_or_create(1, MagicMock())
        await registry.invalidate(1)
        client.shutdown.assert_awaited_once()
        self.assertEqual(registry._clients, {})


if __name__ == "__main__":
    unittest.main()

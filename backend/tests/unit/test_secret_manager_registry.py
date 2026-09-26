"""SecretManagerClientRegistry: lazy build, SM4 freshness, no caching on
failed ensure_started (SM1), invalidate, unknown backend."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from services.secret_manager.config import SecretManagerConnectionConfig
from services.secret_manager.connection_service import SecretManagerConnectionGeneration
from services.secret_manager.exceptions import SecretManagerAuthError, SecretManagerConfigError
from services.secret_manager.registry import SecretManagerClientRegistry, _CachedClient

_TS = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
_TS_LATER = datetime(2026, 9, 16, 13, 0, 0, tzinfo=UTC)


def _cfg(backend: str = "openbao") -> SecretManagerConnectionConfig:
    return SecretManagerConnectionConfig(
        id=1, name="net", backend=backend, verify_ssl=True, backend_config={},
        auth_id="a", auth_secret="b",
    )


def _generation(
    *, is_active: bool = True, updated_at: datetime = _TS, name: str = "net"
) -> SecretManagerConnectionGeneration:
    return SecretManagerConnectionGeneration(
        name=name, is_active=is_active, updated_at=updated_at
    )


def _patch_generation(generation: SecretManagerConnectionGeneration | None):
    service = MagicMock()
    service.get_generation.return_value = generation
    return patch(
        "services.secret_manager.registry.SecretManagerConnectionService",
        return_value=service,
    )


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_backend_is_config_error(self) -> None:
        with (
            _patch_generation(_generation()),
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg("nope"),
            ),
        ):
            with self.assertRaises(SecretManagerConfigError):
                await SecretManagerClientRegistry().get_or_create(1, MagicMock())

    async def test_failed_ensure_started_is_not_cached(self) -> None:
        client = MagicMock()
        client.ensure_started = AsyncMock(side_effect=SecretManagerAuthError("bad"))
        registry = SecretManagerClientRegistry()
        with (
            _patch_generation(_generation()),
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg(),
            ),
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
            _patch_generation(_generation()),
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg(),
            ),
            patch("services.secret_manager.registry._build_client", return_value=client) as build,
        ):
            first = await registry.get_or_create(1, MagicMock())
            second = await registry.get_or_create(1, MagicMock())
        build.assert_called_once()
        self.assertIs(first, second)
        self.assertIs(first, client)

    async def test_invalidate_shuts_client_down(self) -> None:
        client = MagicMock()
        client.ensure_started = AsyncMock()
        client.shutdown = AsyncMock()
        registry = SecretManagerClientRegistry()
        with (
            _patch_generation(_generation()),
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg(),
            ),
            patch("services.secret_manager.registry._build_client", return_value=client),
        ):
            await registry.get_or_create(1, MagicMock())
        await registry.invalidate(1)
        client.shutdown.assert_awaited_once()
        self.assertEqual(registry._clients, {})

    async def test_missing_row_drops_cached_client(self) -> None:
        client = MagicMock()
        client.ensure_started = AsyncMock()
        client.shutdown = AsyncMock()
        registry = SecretManagerClientRegistry()
        with (
            _patch_generation(_generation()),
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg(),
            ),
            patch("services.secret_manager.registry._build_client", return_value=client),
        ):
            await registry.get_or_create(1, MagicMock())
        with _patch_generation(None):
            with self.assertRaisesRegex(ValueError, "connection 1 not found"):
                await registry.get_or_create(1, MagicMock())
        client.shutdown.assert_awaited_once()
        self.assertEqual(registry._clients, {})

    async def test_inactive_row_drops_cached_client_and_does_not_rebuild(self) -> None:
        client = MagicMock()
        client.ensure_started = AsyncMock()
        client.shutdown = AsyncMock()
        registry = SecretManagerClientRegistry()
        with (
            _patch_generation(_generation()),
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg(),
            ) as load,
            patch("services.secret_manager.registry._build_client", return_value=client),
        ):
            await registry.get_or_create(1, MagicMock())
            load.reset_mock()
            with _patch_generation(_generation(is_active=False)):
                with self.assertRaisesRegex(ValueError, "is not active"):
                    await registry.get_or_create(1, MagicMock())
            load.assert_not_called()
        client.shutdown.assert_awaited_once()
        self.assertEqual(registry._clients, {})

    async def test_updated_at_change_rebuilds_client(self) -> None:
        old_client = MagicMock()
        old_client.ensure_started = AsyncMock()
        old_client.shutdown = AsyncMock()
        new_client = MagicMock()
        new_client.ensure_started = AsyncMock()
        registry = SecretManagerClientRegistry()
        with (
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg(),
            ),
            patch(
                "services.secret_manager.registry._build_client",
                side_effect=[old_client, new_client],
            ) as build,
        ):
            with _patch_generation(_generation(updated_at=_TS)):
                first = await registry.get_or_create(1, MagicMock())
            with _patch_generation(_generation(updated_at=_TS_LATER)):
                second = await registry.get_or_create(1, MagicMock())
        self.assertIs(first, old_client)
        self.assertIs(second, new_client)
        self.assertEqual(build.call_count, 2)
        old_client.shutdown.assert_awaited_once()
        new_client.shutdown.assert_not_called()

    async def test_unchanged_updated_at_does_not_call_load_connection_config(self) -> None:
        client = MagicMock()
        client.ensure_started = AsyncMock()
        registry = SecretManagerClientRegistry()
        with (
            _patch_generation(_generation()),
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg(),
            ) as load,
            patch("services.secret_manager.registry._build_client", return_value=client),
        ):
            await registry.get_or_create(1, MagicMock())
            load.reset_mock()
            await registry.get_or_create(1, MagicMock())
            load.assert_not_called()

    async def test_stale_snapshot_does_not_evict_newer_cache(self) -> None:
        """D5b: a get_or_create whose first PK read is behind the cache must
        re-read and return the newer client, not shut it down."""
        newer = MagicMock()
        newer.shutdown = AsyncMock()
        registry = SecretManagerClientRegistry()
        registry._clients[1] = _CachedClient(client=newer, updated_at=_TS_LATER)
        service = MagicMock()
        service.get_generation.side_effect = [
            _generation(updated_at=_TS),
            _generation(updated_at=_TS_LATER),
        ]
        with (
            patch(
                "services.secret_manager.registry.SecretManagerConnectionService",
                return_value=service,
            ),
            patch(
                "services.secret_manager.registry.load_connection_config",
                return_value=_cfg(),
            ) as load,
            patch("services.secret_manager.registry._build_client") as build,
        ):
            got = await registry.get_or_create(1, MagicMock())
        self.assertIs(got, newer)
        newer.shutdown.assert_not_called()
        build.assert_not_called()
        load.assert_not_called()
        self.assertEqual(service.get_generation.call_count, 2)


if __name__ == "__main__":
    unittest.main()

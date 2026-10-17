"""The API starts its app services through the same block the Hatchet workers use."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import main


def test_api_lifespan_uses_the_shared_start_all_with_vault_management() -> None:
    calls: list[tuple[tuple, dict]] = []
    events: list[str] = []

    @asynccontextmanager
    async def fake_start_all(*args, **kwargs):
        calls.append((args, kwargs))
        events.append("started")
        try:
            yield
        finally:
            events.append("stopped")

    rbac = MagicMock()
    rbac.role_has_members.return_value = True
    with (
        patch.object(main, "init_db"),
        patch.object(main, "SessionLocal", return_value=MagicMock()),
        patch.object(main, "AuthService"),
        patch.object(main, "seed_rbac"),
        patch.object(main, "RBACService", return_value=rbac),
        patch.object(main, "ensure_ai_assistant_user", return_value=MagicMock(id=1)),
        patch.object(main, "LoggingSettingsService"),
        patch.object(main, "warn_about_orphaned_inventories"),
        patch.object(main, "PluginRegistryService"),
        patch.object(main, "PluginRepository"),
        patch.object(main, "start_all", fake_start_all),
    ):

        async def run() -> None:
            async with main.lifespan(main.app):
                events.append("serving")

        asyncio.run(run())

    assert events == ["started", "serving", "stopped"]
    assert calls == [(("app",), {"with_management": True, "apply_logging": False})]

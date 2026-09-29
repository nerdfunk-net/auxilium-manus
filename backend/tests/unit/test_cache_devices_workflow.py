"""The shared refresh routine behind the cron workflow and the Rebuild button."""

from __future__ import annotations

import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

from hatchet.workflows import cache_devices


def _setting(source_id: str) -> MagicMock:
    return MagicMock(key=f"sources.nautobot.{source_id}")


class RefreshRoutineTests(unittest.IsolatedAsyncioTestCase):
    def _patch(self, stack: ExitStack, *, sources: list[str], configs: dict, service) -> None:
        stack.enter_context(patch("core.database.SessionLocal", MagicMock()))
        stack.enter_context(
            patch(
                "repositories.settings_repository.SettingsRepository.list_all",
                return_value=[_setting(s) for s in sources],
            )
        )
        stack.enter_context(
            patch(
                "services.settings.settings_service.SettingsService.get_source_config",
                side_effect=lambda kind, source_id: configs[source_id],
            )
        )
        stack.enter_context(
            patch(
                "services.settings.source_keys.parse_source_key",
                side_effect=lambda key: ("nautobot", key.rsplit(".", 1)[1]),
            )
        )
        stack.enter_context(
            patch("service_factory.credentials_from_connection", return_value=MagicMock())
        )
        stack.enter_context(
            patch("service_factory.build_nautobot_source_service", return_value=service)
        )

    async def test_refreshes_every_source_and_passes_force_through(self) -> None:
        service = MagicMock()
        service.refresh_bulk_device_cache = AsyncMock(return_value=5)
        configs = {"a": {"url": "http://a", "token": "t"}, "b": {"url": "http://b", "token": "t"}}

        for force in (False, True):
            service.refresh_bulk_device_cache.reset_mock()
            with ExitStack() as stack:
                self._patch(stack, sources=["a", "b"], configs=configs, service=service)
                summary = await cache_devices.refresh_nautobot_device_caches(force=force)

            self.assertEqual(summary, {"sources": 2, "refreshed": 2, "failed": 0, "devices": 10})
            self.assertEqual(service.refresh_bulk_device_cache.await_count, 2)
            for call in service.refresh_bulk_device_cache.await_args_list:
                self.assertEqual(call.kwargs, {"force": force})

    async def test_one_failing_source_does_not_stop_the_others(self) -> None:
        service = MagicMock()
        service.refresh_bulk_device_cache = AsyncMock(side_effect=[RuntimeError("nb down"), 4])
        configs = {"a": {"url": "http://a", "token": "t"}, "b": {"url": "http://b", "token": "t"}}

        with ExitStack() as stack:
            self._patch(stack, sources=["a", "b"], configs=configs, service=service)
            summary = await cache_devices.refresh_nautobot_device_caches(force=True)

        self.assertEqual(summary, {"sources": 2, "refreshed": 1, "failed": 1, "devices": 4})

    async def test_source_without_url_or_token_is_skipped(self) -> None:
        service = MagicMock()
        service.refresh_bulk_device_cache = AsyncMock(return_value=1)
        configs = {"a": {"url": "", "token": "t"}, "b": {"url": "http://b", "token": ""}}

        with ExitStack() as stack:
            self._patch(stack, sources=["a", "b"], configs=configs, service=service)
            summary = await cache_devices.refresh_nautobot_device_caches(force=False)

        service.refresh_bulk_device_cache.assert_not_awaited()
        self.assertEqual(summary, {"sources": 2, "refreshed": 0, "failed": 0, "devices": 0})

    async def test_no_sources_configured(self) -> None:
        with ExitStack() as stack:
            self._patch(stack, sources=[], configs={}, service=MagicMock())
            summary = await cache_devices.refresh_nautobot_device_caches(force=True)

        self.assertEqual(summary, {"sources": 0, "refreshed": 0, "failed": 0, "devices": 0})


class WorkflowDefinitionTests(unittest.TestCase):
    def test_cron_workflow_is_unchanged_and_rebuild_has_no_schedule(self) -> None:
        cron = cache_devices.workflow.to_proto()
        rebuild = cache_devices.rebuild_workflow.to_proto()

        self.assertEqual(cron.name, "RefreshNautobotDeviceCache")
        self.assertEqual(list(cron.cron_triggers), ["*/5 * * * *"])
        self.assertEqual([t.readable_id for t in cron.tasks], ["refresh_all_sources"])
        self.assertEqual(rebuild.name, "RebuildNautobotDeviceCache")
        self.assertEqual(list(rebuild.cron_triggers), [])
        self.assertEqual([t.readable_id for t in rebuild.tasks], ["rebuild_all_sources"])

    def test_rebuild_workflow_is_registered_on_the_worker(self) -> None:
        import inspect

        import hatchet.worker as worker_module

        source = inspect.getsource(worker_module.main)
        self.assertIn("cache_rebuild_workflow", source)


if __name__ == "__main__":
    unittest.main()

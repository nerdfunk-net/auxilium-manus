"""Tests for services/cache/cache_settings_service.py."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from models.cache_settings import CacheSettings
from services.cache.cache_settings_service import CacheSettingsService


def _service(row=None, cache=None) -> CacheSettingsService:
    svc = CacheSettingsService(MagicMock(), cache)
    svc._repo = MagicMock()
    svc._repo.get_by_key.return_value = row
    return svc


class CacheSettingsServiceTests(unittest.TestCase):
    def test_get_settings_defaults_when_no_row(self) -> None:
        resp = _service(cache=MagicMock()).get_settings()
        self.assertTrue(resp.enabled)
        self.assertEqual(resp.device_ttl_seconds, 1800)
        self.assertTrue(resp.redis_connected)

    def test_get_settings_reads_stored_row(self) -> None:
        row = MagicMock(value={"enabled": False, "device_ttl_seconds": 60})
        resp = _service(row=row, cache=None).get_settings()
        self.assertFalse(resp.enabled)
        self.assertEqual(resp.device_ttl_seconds, 60)
        self.assertFalse(resp.redis_connected)

    def test_update_settings_creates_when_absent(self) -> None:
        svc = _service(row=None, cache=MagicMock())
        resp = svc.update_settings(CacheSettings(enabled=False, device_ttl_seconds=120))
        svc._repo.create.assert_called_once()
        svc._repo.update.assert_not_called()
        self.assertFalse(resp.enabled)
        self.assertEqual(resp.device_ttl_seconds, 120)

    def test_update_settings_updates_existing_row(self) -> None:
        row = MagicMock()
        svc = _service(row=row, cache=MagicMock())
        svc.update_settings(CacheSettings(enabled=True, device_ttl_seconds=900))
        svc._repo.update.assert_called_once()
        svc._repo.create.assert_not_called()

    def test_get_stats_without_cache(self) -> None:
        resp = _service(cache=None).get_stats()
        self.assertFalse(resp.connected)

    def test_get_stats_maps_cache_payload(self) -> None:
        cache = MagicMock()
        cache.stats.return_value = {
            "overview": {"total_items": 3},
            "performance": {"cache_hits": 5},
            "namespaces": {"n": {"count": 1}},
        }
        resp = _service(cache=cache).get_stats()
        self.assertTrue(resp.connected)
        self.assertEqual(resp.overview, {"total_items": 3})
        self.assertEqual(resp.performance, {"cache_hits": 5})

    def test_get_stats_error_path(self) -> None:
        cache = MagicMock()
        cache.stats.side_effect = RuntimeError("down")
        self.assertFalse(_service(cache=cache).get_stats().connected)

    def test_clear_without_cache(self) -> None:
        self.assertEqual(_service(cache=None).clear().cleared, 0)

    def test_clear_returns_count(self) -> None:
        cache = MagicMock()
        cache.clear_all.return_value = 12
        self.assertEqual(_service(cache=cache).clear().cleared, 12)

    def test_clear_error_path(self) -> None:
        cache = MagicMock()
        cache.clear_all.side_effect = RuntimeError("down")
        self.assertEqual(_service(cache=cache).clear().cleared, 0)


if __name__ == "__main__":
    unittest.main()

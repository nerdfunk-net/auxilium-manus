"""Tests for the report-data retention sweep."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.report_data.report_data_service import ReportDataService


class PurgeOlderThanDaysTests(unittest.TestCase):
    def _service(self) -> tuple[ReportDataService, MagicMock]:
        service = ReportDataService(MagicMock())
        repo = MagicMock()
        repo.purge_older_than.return_value = 7
        service.repository = repo
        return service, repo

    def test_zero_or_negative_days_keeps_everything(self) -> None:
        service, repo = self._service()

        self.assertEqual(service.purge_older_than_days(0), 0)
        self.assertEqual(service.purge_older_than_days(-1), 0)
        repo.purge_older_than.assert_not_called()

    def test_positive_days_delegates_with_a_cutoff(self) -> None:
        service, repo = self._service()

        self.assertEqual(service.purge_older_than_days(30, batch_size=100), 7)

        cutoff = repo.purge_older_than.call_args.args[0]
        self.assertIsNotNone(cutoff.tzinfo)
        self.assertEqual(repo.purge_older_than.call_args.kwargs, {"batch_size": 100})


class ConfigTests(unittest.TestCase):
    def test_default_and_validation(self) -> None:
        from core.config import Settings

        with patch.dict("os.environ", {"REPORT_DATA_RETENTION_DAYS": "-1"}):
            with self.assertRaises(RuntimeError):
                Settings()
        with patch.dict("os.environ", {"REPORT_DATA_RETENTION_DAYS": "45"}):
            self.assertEqual(Settings().report_data_retention_days, 45)


if __name__ == "__main__":
    unittest.main()

"""Tests for services/git/csv_service.py."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from core.domain_exceptions import AccessDeniedError, NotFoundError, ValidationFailedError
from services.git.csv_service import GitCsvService


class GitCsvServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "devices.csv").write_text("name,ip\nr1,10.0.0.1\n")
        (self.root / "sub").mkdir()
        (self.root / "sub" / "more.csv").write_text("a;b\n1;2\n")
        (self.root / "notes.txt").write_text("ignore me\n")

        self.repos = MagicMock()
        self.repos.get_repository.return_value = {"id": 1, "name": "csvrepo"}

        p = patch("services.git.csv_service.git_repo_path", return_value=self.root)
        self.addCleanup(p.stop)
        p.start()
        self.service = GitCsvService(self.repos)

    def test_list_csv_files_finds_all_csvs_sorted(self) -> None:
        out = self.service.list_csv_files(1)
        paths = [f["path"] for f in out["data"]["files"]]
        self.assertEqual(paths, ["devices.csv", "sub/more.csv"])
        self.assertEqual(out["data"]["total_count"], 2)

    def test_list_csv_files_query_filter(self) -> None:
        out = self.service.list_csv_files(1, query="more")
        self.assertEqual(len(out["data"]["files"]), 1)

    def test_list_csv_files_limit(self) -> None:
        out = self.service.list_csv_files(1, limit=1)
        self.assertEqual(len(out["data"]["files"]), 1)
        self.assertEqual(out["data"]["total_count"], 2)

    def test_list_csv_files_missing_dir_returns_empty(self) -> None:
        with patch(
            "services.git.csv_service.git_repo_path", return_value=self.root / "gone"
        ):
            out = self.service.list_csv_files(1)
        self.assertEqual(out["data"]["files"], [])

    def test_list_csv_files_unknown_repo(self) -> None:
        self.repos.get_repository.return_value = None
        with self.assertRaises(NotFoundError):
            self.service.list_csv_files(1)

    def test_list_csv_files_wraps_unexpected_errors(self) -> None:
        self.repos.get_repository.side_effect = RuntimeError("db boom")
        with self.assertRaises(HTTPException):
            self.service.list_csv_files(1)

    def test_get_csv_headers_default_delimiter(self) -> None:
        out = self.service.get_csv_headers(1, "devices.csv")
        self.assertEqual(out["headers"], ["name", "ip"])

    def test_get_csv_headers_custom_delimiter(self) -> None:
        out = self.service.get_csv_headers(1, "sub/more.csv", delimiter=";")
        self.assertEqual(out["headers"], ["a", "b"])

    def test_get_csv_headers_path_escape_denied(self) -> None:
        with self.assertRaises(AccessDeniedError):
            self.service.get_csv_headers(1, "../../etc/passwd")

    def test_get_csv_headers_sibling_repo_denied(self) -> None:
        # S8: a sibling dir sharing a name prefix must not be treated as in-repo.
        sibling = self.root.parent / f"{self.root.name}-evil"
        sibling.mkdir()
        self.addCleanup(shutil.rmtree, sibling, ignore_errors=True)
        (sibling / "secret.csv").write_text("x,y\n1,2\n")
        with self.assertRaises(AccessDeniedError):
            self.service.get_csv_headers(1, f"../{sibling.name}/secret.csv")

    def test_get_csv_headers_missing_file(self) -> None:
        with self.assertRaises(NotFoundError):
            self.service.get_csv_headers(1, "absent.csv")

    def test_get_csv_headers_not_a_file(self) -> None:
        with self.assertRaises(ValidationFailedError):
            self.service.get_csv_headers(1, "sub")

    def test_get_csv_headers_missing_repo_dir(self) -> None:
        with patch(
            "services.git.csv_service.git_repo_path", return_value=self.root / "gone"
        ):
            with self.assertRaises(NotFoundError):
                self.service.get_csv_headers(1, "devices.csv")


if __name__ == "__main__":
    unittest.main()

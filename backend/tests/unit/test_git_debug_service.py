"""Tests for services/git/debug_service.py against real throwaway repos."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from _git_repo_builder import make_repo_with_remote, make_working_repo
from git import Repo

from services.git.debug_service import (
    GitDebugService,
    _debug_result,
    _push_error_suggestion,
    _repository_info_section,
    _require_push_auth,
    _restore_origin_url,
)

_REPO = {
    "id": 1,
    "name": "dbg",
    "url": "https://example.com/dbg.git",
    "branch": "main",
    "is_active": True,
    "auth_type": "token",
    "verify_ssl": True,
}


class PureHelperTests(unittest.TestCase):
    def test_repository_info_section(self) -> None:
        section = _repository_info_section(_REPO)
        self.assertEqual(section["name"], "dbg")
        self.assertTrue(section["verify_ssl"])

    def test_debug_result_wraps_details(self) -> None:
        out = _debug_result(False, "nope", error="x")
        self.assertEqual(out, {"success": False, "message": "nope", "details": {"error": "x"}})

    def test_require_push_auth_variants(self) -> None:
        self.assertIsNone(_require_push_auth(_REPO, "u", "t", None))
        self.assertIsNotNone(_require_push_auth(_REPO, None, None, None))
        self.assertIsNotNone(
            _require_push_auth({**_REPO, "auth_type": "ssh_key"}, None, None, None)
        )
        self.assertIsNotNone(
            _require_push_auth({**_REPO, "auth_type": "none"}, None, None, None)
        )

    def test_push_error_suggestion_variants(self) -> None:
        self.assertIn("permissions", _push_error_suggestion("Permission denied").lower())
        self.assertIn("network", _push_error_suggestion("Could not resolve host").lower())
        self.assertIn("invalid", _push_error_suggestion("Authentication failed").lower())
        self.assertIn("configuration", _push_error_suggestion("weird").lower())

    def test_restore_origin_url_skips_ssh(self) -> None:
        origin = MagicMock()
        _restore_origin_url(origin, "orig", "ssh_key")
        origin.set_url.assert_not_called()
        _restore_origin_url(origin, "orig", "token")
        origin.set_url.assert_called_once_with("orig")


class DebugFileOpsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo_dir = make_working_repo(Path(self._tmp.name))
        self.repo = Repo(self.repo_dir)
        self.repos = MagicMock()
        self.repos.get_repository.return_value = dict(_REPO)

        p = patch(
            "services.git.debug_service.get_git_repo_by_id", return_value=self.repo
        )
        self.addCleanup(p.stop)
        p.start()
        self.service = GitDebugService(self.repos)

    def test_unknown_repo_raises(self) -> None:
        self.repos.get_repository.return_value = None
        with self.assertRaises(ValueError):
            self.service.test_read(1)

    def test_read_before_write_reports_absent(self) -> None:
        out = self.service.test_read(1)
        self.assertFalse(out["success"])
        self.assertFalse(out["details"]["exists"])

    def test_write_then_read_then_delete_roundtrip(self) -> None:
        write_out = self.service.test_write(1)
        self.assertTrue(write_out["success"])

        read_out = self.service.test_read(1)
        self.assertTrue(read_out["success"])
        self.assertIn("Cockpit Debug Test", read_out["details"]["content"])

        del_out = self.service.test_delete(1)
        self.assertTrue(del_out["success"])
        self.assertFalse((self.repo_dir / ".cockpit_debug_test.txt").exists())

    def test_delete_when_absent(self) -> None:
        out = self.service.test_delete(1)
        self.assertFalse(out["success"])

    def test_push_requires_credentials(self) -> None:
        auth = MagicMock()
        auth.resolve_credentials.return_value = (None, None, None)
        out = self.service.test_push(1, auth)
        self.assertFalse(out["success"])
        self.assertEqual(out["details"]["error_type"], "AuthenticationRequired")


class DebugPushTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.work, self.bare = make_repo_with_remote(Path(self._tmp.name))
        self.repo = Repo(self.work)
        self.repos = MagicMock()
        self.repos.get_repository.return_value = {
            **_REPO,
            "url": f"file://{self.bare}",
        }
        p = patch(
            "services.git.debug_service.get_git_repo_by_id", return_value=self.repo
        )
        self.addCleanup(p.stop)
        p.start()
        self.service = GitDebugService(self.repos)

    def test_push_roundtrip_to_file_remote(self) -> None:
        file_url = f"file://{self.bare}"

        @contextmanager
        def fake_env(repository):
            yield (file_url, "u", "t", None)

        auth = MagicMock()
        auth.resolve_credentials.return_value = ("u", "t", None)
        auth.setup_auth_environment.side_effect = fake_env

        out = self.service.test_push(1, auth)
        self.assertTrue(out["success"], out)
        self.assertIn(".cockpit_debug_test.txt", Repo(self.bare).git.show("--stat", "HEAD"))


class DebugDiagnosticsTests(unittest.TestCase):
    def test_get_diagnostics_assembles_sections(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo_dir = make_working_repo(Path(tmp.name))
        repos = MagicMock()
        repos.get_repository.return_value = dict(_REPO)
        auth = MagicMock()
        auth.resolve_credentials.return_value = ("u", "t", None)

        with patch(
            "services.git.debug_service.get_git_repo_by_id", return_value=Repo(repo_dir)
        ):
            out = GitDebugService(repos).get_diagnostics(1, auth)

        self.assertTrue(out["success"])
        self.assertEqual(out["diagnostics"]["repository_info"]["name"], "dbg")
        self.assertIn("ssl_info", out["diagnostics"])


if __name__ == "__main__":
    unittest.main()

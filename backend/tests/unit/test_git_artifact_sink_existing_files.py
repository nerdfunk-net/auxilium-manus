"""GitArtifactSink.existing_files: read-only listing of an export folder."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.artifacts.sinks.git_sink import GitArtifactSink


def _sink(subdirectory: str = "aci") -> GitArtifactSink:
    with patch("service_factory.build_git_service"):
        return GitArtifactSink({"id": 1, "name": "r"}, repository_subdirectory=subdirectory)


class ExistingFilesTests(unittest.TestCase):
    def test_lists_the_files_directly_in_the_folder_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / "aci" / "tenants"
            (folder / "sub").mkdir(parents=True)
            (folder / "B.json").write_text("{}")
            (folder / "A.json").write_text("{}")
            with patch("services.artifacts.sinks.git_sink.get_repo_path", return_value=Path(root)):
                self.assertEqual(_sink().existing_files("tenants"), ("A.json", "B.json"))

    def test_a_missing_folder_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with patch("services.artifacts.sinks.git_sink.get_repo_path", return_value=Path(root)):
                self.assertEqual(_sink().existing_files("tenants"), ())

    def test_a_path_leaving_the_export_folder_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with patch("services.artifacts.sinks.git_sink.get_repo_path", return_value=Path(root)):
                for bad in ("../x", "a/../../x"):
                    with self.subTest(path=bad), self.assertRaises(ValueError):
                        _sink().existing_files(bad)

    def test_a_leading_slash_stays_inside_the_export_folder_like_a_write(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "aci" / "etc").mkdir(parents=True)
            (Path(root) / "aci" / "etc" / "x.json").write_text("{}")
            with patch("services.artifacts.sinks.git_sink.get_repo_path", return_value=Path(root)):
                self.assertEqual(_sink().existing_files("/etc"), ("x.json",))


class SymlinkTests(unittest.TestCase):
    def test_a_symlinked_folder_is_refused_not_followed(self) -> None:
        from core.domain_exceptions import AccessDeniedError

        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            (Path(outside) / "secret-name.json").write_text("{}")
            (Path(root) / "aci").mkdir()
            (Path(root) / "aci" / "tenants").symlink_to(outside, target_is_directory=True)
            with patch("services.artifacts.sinks.git_sink.get_repo_path", return_value=Path(root)):
                with self.assertRaises(AccessDeniedError):
                    _sink().existing_files("tenants")

    def test_a_symlinked_parent_is_refused(self) -> None:
        from core.domain_exceptions import AccessDeniedError

        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            (Path(outside) / "tenants").mkdir()
            (Path(outside) / "tenants" / "x.json").write_text("{}")
            (Path(root) / "aci").symlink_to(outside, target_is_directory=True)
            with patch("services.artifacts.sinks.git_sink.get_repo_path", return_value=Path(root)):
                with self.assertRaises(AccessDeniedError):
                    _sink().existing_files("tenants")

    def test_a_symlinked_file_is_not_listed(self) -> None:
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            folder = Path(root) / "aci" / "tenants"
            folder.mkdir(parents=True)
            (folder / "real.json").write_text("{}")
            (Path(outside) / "other.json").write_text("{}")
            (folder / "link.json").symlink_to(Path(outside) / "other.json")
            with patch("services.artifacts.sinks.git_sink.get_repo_path", return_value=Path(root)):
                self.assertEqual(_sink().existing_files("tenants"), ("real.json",))

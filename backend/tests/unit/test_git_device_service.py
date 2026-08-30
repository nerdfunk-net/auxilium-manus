"""Tests for services/git/device_service.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.git.device_service import (
    GitDeviceService,
    _find_files,
    _parse_device_entry,
    _parse_yaml_file,
)


class ParseDeviceEntryTests(unittest.TestCase):
    def test_non_dict_returns_none(self) -> None:
        self.assertIsNone(_parse_device_entry("nope"))

    def test_missing_name_returns_none(self) -> None:
        self.assertIsNone(_parse_device_entry({"primary_ip4": "10.0.0.1"}))

    def test_full_entry_shape(self) -> None:
        parsed = _parse_device_entry(
            {"name": "r1", "primary_ip4": "10.0.0.1/24", "network_driver": "ios"}
        )
        self.assertEqual(parsed["name"], "r1")
        self.assertEqual(parsed["primary_ip4"], {"address": "10.0.0.1/24"})
        self.assertEqual(parsed["platform"]["network_driver"], "ios")

    def test_entry_without_ip(self) -> None:
        parsed = _parse_device_entry({"name": "r2"})
        self.assertIsNone(parsed["primary_ip4"])


class ParseYamlFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _write(self, text: str) -> Path:
        p = self.root / "d.yaml"
        p.write_text(text)
        return p

    def test_valid_devices_list(self) -> None:
        out = _parse_yaml_file(self._write("devices:\n  - name: r1\n  - name: r2\n"))
        self.assertEqual([d["name"] for d in out], ["r1", "r2"])

    def test_devices_as_single_dict_is_wrapped(self) -> None:
        out = _parse_yaml_file(self._write("devices:\n  name: solo\n"))
        self.assertEqual(out[0]["name"], "solo")

    def test_non_dict_root_returns_empty(self) -> None:
        self.assertEqual(_parse_yaml_file(self._write("- just\n- a\n- list\n")), [])

    def test_devices_not_a_list_returns_empty(self) -> None:
        self.assertEqual(_parse_yaml_file(self._write("devices: 42\n")), [])

    def test_unparseable_yaml_returns_empty(self) -> None:
        self.assertEqual(_parse_yaml_file(self._write("key: : :\n::\n")), [])


class FindFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "a.yaml").write_text("devices: []\n")
        (self.root / "nested").mkdir()
        (self.root / "nested" / "b.yaml").write_text("devices: []\n")

    def test_recursive_glob_finds_nested(self) -> None:
        found = _find_files(self.root, "", "*.yaml")
        names = sorted(p.name for p in found)
        self.assertEqual(names, ["a.yaml", "b.yaml"])

    def test_leading_slash_directory_is_treated_relative(self) -> None:
        found = _find_files(self.root, "/nested", "*.yaml")
        self.assertEqual([p.name for p in found], ["b.yaml"])


class FetchDevicesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo_dir = Path(self._tmp.name) / "repo"
        (self.repo_dir / "inv").mkdir(parents=True)
        (self.repo_dir / "inv" / "site.yaml").write_text(
            "devices:\n  - name: r1\n    primary_ip4: 10.0.0.1\n  - name: r2\n"
        )

    def test_fetch_devices_parses_matched_files(self) -> None:
        with patch(
            "services.git.device_service.clone_or_pull", return_value=self.repo_dir
        ):
            devices, files_read = GitDeviceService().fetch_devices(
                {"name": "inv-repo"}, "*.yaml", directory="inv"
            )
        self.assertEqual(files_read, 1)
        self.assertEqual({d["name"] for d in devices}, {"r1", "r2"})

    def test_fetch_devices_warns_on_leading_slash_directory(self) -> None:
        with patch(
            "services.git.device_service.clone_or_pull", return_value=self.repo_dir
        ):
            devices, _ = GitDeviceService().fetch_devices(
                {"name": "inv-repo"}, "*.yaml", directory="/inv"
            )
        self.assertEqual(len(devices), 2)


if __name__ == "__main__":
    unittest.main()

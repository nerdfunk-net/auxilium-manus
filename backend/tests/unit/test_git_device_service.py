"""Tests for services/git/device_service.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.git.device_service import (
    GitDeviceService,
    _find_files,
    _parse_yaml_file,
    _read_yaml_entries,
)


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

    def test_non_dict_entries_are_dropped(self) -> None:
        out = _parse_yaml_file(self._write("devices:\n  - name: r1\n  - plain\n"))
        self.assertEqual(out, [{"name": "r1"}])

    def test_root_list_of_devices_is_accepted(self) -> None:
        out = _parse_yaml_file(self._write("---\n- name: r1\n- name: r2\n"))
        self.assertEqual([d["name"] for d in out], ["r1", "r2"])

    def test_scalar_root_returns_empty_with_problem(self) -> None:
        entries, problem = _read_yaml_entries(self._write("just text\n"))
        self.assertEqual(entries, [])
        self.assertIn("expected a list of devices", problem)

    def test_unparseable_reports_problem(self) -> None:
        _, problem = _read_yaml_entries(self._write("key: : :\n::\n"))
        self.assertIn("not valid YAML", problem)

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
        with patch("services.git.device_service.clone_or_pull", return_value=self.repo_dir):
            devices, files_read = GitDeviceService().fetch_devices(
                {"name": "inv-repo"}, "*.yaml", directory="inv"
            )
        self.assertEqual(files_read, 1)
        self.assertEqual({d["name"] for d in devices}, {"r1", "r2"})

    def test_fetch_devices_warns_on_leading_slash_directory(self) -> None:
        with patch("services.git.device_service.clone_or_pull", return_value=self.repo_dir):
            devices, _ = GitDeviceService().fetch_devices(
                {"name": "inv-repo"}, "*.yaml", directory="/inv"
            )
        self.assertEqual(len(devices), 2)

    def _fetch_records(self, mapping):
        with patch("services.git.device_service.clone_or_pull", return_value=self.repo_dir):
            return GitDeviceService().fetch_records(
                {"name": "inv-repo"}, "*.yaml", directory="inv", device_mapping=mapping
            )

    def test_default_mapping_shape(self) -> None:
        result = self._fetch_records(None)
        first = next(r.mapped for r in result.records if r.mapped["name"] == "r1")
        self.assertEqual(first["primary_ip4"], {"address": "10.0.0.1"})

    def test_custom_mapping_and_available_keys(self) -> None:
        (self.repo_dir / "inv" / "site.yaml").write_text(
            "devices:\n  - device_name: r1\n    site: City A\n  - site: orphan\n"
        )
        result = self._fetch_records(
            [
                {"source": "device_name", "target": "name"},
                {"source": "site", "target": "location.name"},
            ]
        )
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].mapped, {"name": "r1", "location": {"name": "City A"}})
        self.assertEqual(result.records[0].raw["device_name"], "r1")
        self.assertEqual(result.available_keys, ["device_name", "site"])

    def test_unmapped_name_entries_produce_warning(self) -> None:
        result = self._fetch_records([{"source": "hostname", "target": "name"}])
        self.assertEqual(result.records, [])
        self.assertTrue(any("'hostname'" in w for w in result.warnings))

    def test_no_files_produces_warning(self) -> None:
        with patch("services.git.device_service.clone_or_pull", return_value=self.repo_dir):
            result = GitDeviceService().fetch_records({"name": "x"}, "*.nope", directory="inv")
        self.assertTrue(any("No file matching" in w for w in result.warnings))

    def test_invalid_mapping_raises_before_git_work(self) -> None:
        with patch("services.git.device_service.clone_or_pull") as clone:
            with self.assertRaises(ValueError):
                GitDeviceService().fetch_records(
                    {"name": "x"}, "*.yaml", device_mapping=[{"source": "a", "target": "bogus"}]
                )
        clone.assert_not_called()


class FetchCsvRecordsTests(unittest.TestCase):
    HEADER = (
        "name;ip_address;role;status;location;network_driver;"
        "interface_name;interface_ip_address;cf_snmp_credentials\n"
    )
    MAPPING = [
        {"source": "name", "target": "name"},
        {"source": "ip_address", "target": "primary_ip4.address"},
        {"source": "role", "target": "role.name"},
        {"source": "status", "target": "status.name"},
        {"source": "location", "target": "location.name"},
        {"source": "network_driver", "target": "platform.network_driver"},
        {"source": "interface_name", "target": "interfaces.name"},
        {"source": "interface_ip_address", "target": "interfaces.ip_addresses.address"},
    ]

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo_dir = Path(self._tmp.name)

    def _fetch(self, text: str, **kwargs):
        (self.repo_dir / "d.csv").write_text(text)
        options = {"file_format": "csv", "device_mapping": self.MAPPING, **kwargs}
        with patch("services.git.device_service.clone_or_pull", return_value=self.repo_dir):
            return GitDeviceService().fetch_records({"name": "r"}, "*.csv", **options)

    def test_simple_csv_one_device_per_line(self) -> None:
        result = self._fetch(
            self.HEADER
            + "r1;10.0.0.1/24;Network;Active;A;cisco_ios;;;secret\n"
            + "r2;10.0.0.2/24;Edge;Active;B;cisco_ios;;;\n"
        )
        self.assertEqual([r.mapped["name"] for r in result.records], ["r1", "r2"])
        # cf_ columns are mapped implicitly; empty custom fields are ignored.
        self.assertEqual(result.records[0].mapped["custom_fields"], {"snmp_credentials": "secret"})
        self.assertNotIn("custom_fields", result.records[1].mapped)
        self.assertIn("cf_snmp_credentials", result.available_keys)
        self.assertEqual(result.warnings, [])

    def test_multiline_csv_merges_lines_per_device(self) -> None:
        result = self._fetch(
            self.HEADER
            + "LAB;192.168.178.240/24;network;Active;CityA;cisco_ios;;;\n"
            + "LAB;;;;;;Ethernet0/0;192.168.178.240/24;\n"
            + "LAB;;;;;;Ethernet0/1;192.168.179.240/24;\n",
            csv_multiline=True,
        )
        self.assertEqual(len(result.records), 1)
        mapped = result.records[0].mapped
        self.assertEqual(mapped["location"], {"name": "CityA"})
        self.assertEqual([i["name"] for i in mapped["interfaces"]], ["Ethernet0/0", "Ethernet0/1"])

    def test_same_names_without_multiline_stay_separate_and_warn(self) -> None:
        result = self._fetch(self.HEADER + "A;;;;;;;;\nA;;;;;;;;\n")
        self.assertEqual(len(result.records), 2)
        self.assertTrue(any("same name" in w for w in result.warnings))

    def test_ragged_line_is_reported(self) -> None:
        result = self._fetch(self.HEADER + "LAB;;;;;Ethernet0/0;10.0.0.1/24\n")
        self.assertTrue(any("line 2" in w for w in result.warnings))

    def test_other_delimiter(self) -> None:
        result = self._fetch("name,role\nr1,x\n", csv_delimiter=",", device_mapping=None)
        self.assertEqual(result.records[0].mapped["name"], "r1")

    def test_invalid_format_and_delimiter_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._fetch("name\nr\n", file_format="xml")
        with self.assertRaises(ValueError):
            self._fetch("name\nr\n", csv_delimiter="abc")

    def test_yaml_cf_keys_are_mapped_implicitly(self) -> None:
        (self.repo_dir / "d.yaml").write_text("devices:\n  - name: r1\n    cf_net: lab\n")
        with patch("services.git.device_service.clone_or_pull", return_value=self.repo_dir):
            result = GitDeviceService().fetch_records({"name": "r"}, "*.yaml")
        self.assertEqual(result.records[0].mapped["custom_fields"], {"net": "lab"})


if __name__ == "__main__":
    unittest.main()

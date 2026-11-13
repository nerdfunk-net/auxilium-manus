"""CSV export of a snapshot's section data (the raw data next to the PDF)."""

from __future__ import annotations

import csv
import io
import unittest
import zipfile
from typing import Any

from models.report_definitions import SnapshotContent
from services.reports.csv_export import NothingToExportError, snapshot_csv


def section(sid: str, *, rows: list[list[Any]] | None = None, error: str | None = None) -> dict:
    return {
        "section": {
            "id": sid,
            "title": sid.title(),
            "text": None,
            "presentation": "table",
            "query": {"source": "nautobot", "dataset": "devices"},
        },
        "status": "error" if error else "ok",
        "error": error,
        "result": None
        if error
        else {
            "columns": [
                {"key": "device_name", "label": "device_name", "type": "string"},
                {"key": "serial", "label": "serial", "type": "string"},
            ],
            "rows": rows or [],
            "truncated": False,
        },
        "truncated": False,
    }


def content(*sections: dict, name: str = "Serial numbers") -> SnapshotContent:
    return SnapshotContent.model_validate(
        {"name": name, "description": None, "sections": list(sections)}
    )


def parse(data: bytes) -> list[list[str]]:
    text = data.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


class SingleSectionTests(unittest.TestCase):
    def test_one_section_is_a_csv_with_header_and_bom(self) -> None:
        export = snapshot_csv(content(section("s1", rows=[["sw1", "S1"], ["sw2", None]])))
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(export.filename, "Serial-numbers.csv")
        self.assertTrue(export.data.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(
            parse(export.data), [["device_name", "serial"], ["sw1", "S1"], ["sw2", ""]]
        )

    def test_cells_that_start_a_formula_are_defused(self) -> None:
        export = snapshot_csv(content(section("s1", rows=[["=cmd()", "+1"], ["@x", "-5"]])))
        self.assertEqual(parse(export.data)[1:], [["'=cmd()", "'+1"], ["'@x", "'-5"]])

    def test_numbers_are_not_touched(self) -> None:
        export = snapshot_csv(content(section("s1", rows=[["a", -5], ["b", 2.5]])))
        self.assertEqual(parse(export.data)[1:], [["a", "-5"], ["b", "2.5"]])


class MultiSectionTests(unittest.TestCase):
    def test_several_sections_become_a_zip_of_csv_files(self) -> None:
        export = snapshot_csv(
            content(section("per-site", rows=[["a", "1"]]), section("totals", rows=[["b", "2"]]))
        )
        self.assertEqual(export.media_type, "application/zip")
        self.assertEqual(export.filename, "Serial-numbers.zip")
        with zipfile.ZipFile(io.BytesIO(export.data)) as archive:
            self.assertEqual(archive.namelist(), ["per-site.csv", "totals.csv"])
            self.assertEqual(parse(archive.read("totals.csv"))[1], ["b", "2"])

    def test_failed_sections_are_left_out(self) -> None:
        export = snapshot_csv(
            content(section("bad", error="boom"), section("good", rows=[["a", "1"]]))
        )
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(parse(export.data)[1], ["a", "1"])

    def test_nothing_to_export(self) -> None:
        with self.assertRaises(NothingToExportError):
            snapshot_csv(content(section("bad", error="boom")))


if __name__ == "__main__":
    unittest.main()

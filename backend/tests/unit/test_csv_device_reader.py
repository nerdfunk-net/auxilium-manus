"""Tests for services/git/csv_device_reader.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.git.csv_device_reader import MAX_CSV_BYTES, read_csv_rows


class ReadCsvRowsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _write(self, text: str, *, encoding: str = "utf-8") -> Path:
        path = self.root / "d.csv"
        path.write_bytes(text.encode(encoding))
        return path

    def test_semicolon_rows_become_dicts(self) -> None:
        rows, problems = read_csv_rows(self._write("name;role\nr1;Network\nr2;Edge\n"), ";")
        self.assertEqual(rows, [{"name": "r1", "role": "Network"}, {"name": "r2", "role": "Edge"}])
        self.assertEqual(problems, [])

    def test_other_delimiters(self) -> None:
        for delimiter in (",", "\t", "|"):
            with self.subTest(delimiter=delimiter):
                text = delimiter.join(["name", "role"]) + "\n" + delimiter.join(["r1", "x"]) + "\n"
                rows, _ = read_csv_rows(self._write(text), delimiter)
                self.assertEqual(rows, [{"name": "r1", "role": "x"}])

    def test_utf8_bom_is_stripped_from_first_header(self) -> None:
        rows, _ = read_csv_rows(self._write("name;role\nr1;x\n", encoding="utf-8-sig"), ";")
        self.assertEqual(list(rows[0]), ["name", "role"])

    def test_quoted_field_with_delimiter(self) -> None:
        rows, _ = read_csv_rows(self._write('name;desc\nr1;"a;b"\n'), ";")
        self.assertEqual(rows[0]["desc"], "a;b")

    def test_blank_lines_skipped_and_values_stripped(self) -> None:
        rows, problems = read_csv_rows(self._write("name ; role\n\n r1 ; x \n;;\n"), ";")
        self.assertEqual(rows, [{"name": "r1", "role": "x"}])
        self.assertEqual(problems, [])

    def test_too_few_fields_warns_with_line_number(self) -> None:
        text = "a;b;c;d\n1;2;3;4\nx;;y\n"
        rows, problems = read_csv_rows(self._write(text), ";")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1], {"a": "x", "b": "", "c": "y", "d": ""})
        self.assertEqual(len(problems), 1)
        self.assertIn("line 3", problems[0])
        self.assertIn("3 fields", problems[0])
        self.assertIn("expected 4", problems[0])

    def test_too_many_fields_warns_and_truncates(self) -> None:
        rows, problems = read_csv_rows(self._write("a;b\n1;2;3\n"), ";")
        self.assertEqual(rows, [{"a": "1", "b": "2"}])
        self.assertEqual(len(problems), 1)

    def test_ragged_warnings_are_capped(self) -> None:
        body = "".join("x\n" for _ in range(20))
        _, problems = read_csv_rows(self._write("a;b\n" + body), ";")
        self.assertEqual(len(problems), 6)
        self.assertIn("15 more", problems[-1])

    def test_empty_file(self) -> None:
        rows, problems = read_csv_rows(self._write(""), ";")
        self.assertEqual(rows, [])
        self.assertIn("empty", problems[0])

    def test_invalid_encoding_reported(self) -> None:
        rows, problems = read_csv_rows(self._write("name\n\xe9\n", encoding="latin-1"), ";")
        self.assertEqual(rows, [])
        self.assertIn("UTF-8", problems[0])

    def test_oversized_file_rejected(self) -> None:
        path = self._write("name\n")
        with open(path, "ab") as fh:
            fh.truncate(MAX_CSV_BYTES + 1)
        rows, problems = read_csv_rows(path, ";")
        self.assertEqual(rows, [])
        self.assertIn("too large", problems[0])


if __name__ == "__main__":
    unittest.main()

"""Tests for the shared CSV lookup core (parse + match + reconcile)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from services.csv_lookup import (
    CsvLookupError,
    CsvRow,
    KeyColumnNotFoundError,
    ReconcileTooLargeError,
    RowIndex,
    ValueItem,
    normalize_ip_host,
    parse_csv_rows,
    parse_delimiter,
    reconcile,
)


def _rows(*keys: str) -> list[CsvRow]:
    return [CsvRow(key=key, values={"data": f"d-{key}"}) for key in keys]


def _items(*values: str | None) -> list[ValueItem]:
    return [
        ValueItem(id=f"id{i}", value=value, info={"name": f"dev{i}"})
        for i, value in enumerate(values)
    ]


class ParseTests(unittest.TestCase):
    def test_rows_drop_key_and_empty_cells(self) -> None:
        rows = parse_csv_rows("serial;data;site\n1;a;\n2;;x\n", key_column="serial")
        self.assertEqual(rows[0], CsvRow(key="1", values={"data": "a"}))
        self.assertEqual(rows[1], CsvRow(key="2", values={"site": "x"}))

    def test_short_row_and_blank_lines(self) -> None:
        rows = parse_csv_rows("serial;data;site\n\n1;a\n  ;  ;  \n", key_column="serial")
        self.assertEqual(rows, [CsvRow(key="1", values={"data": "a"})])

    def test_bom_trim_and_delimiter(self) -> None:
        rows = parse_csv_rows("﻿serial,data\n 1 , x \n", key_column="serial", delimiter=",")
        self.assertEqual(rows, [CsvRow(key="1", values={"data": "x"})])

    def test_header_errors(self) -> None:
        with self.assertRaisesRegex(CsvLookupError, "empty"):
            parse_csv_rows("", key_column="serial", label="a.csv")
        with self.assertRaisesRegex(CsvLookupError, "duplicate"):
            parse_csv_rows("serial;a;a\n", key_column="serial")
        with self.assertRaisesRegex(CsvLookupError, "key column 'nope'") as caught:
            parse_csv_rows("serial;a\n", key_column="nope")
        self.assertIsInstance(caught.exception, KeyColumnNotFoundError)
        self.assertEqual(caught.exception.columns, ("serial", "a"))

    def test_row_cap(self) -> None:
        with patch("services.csv_lookup.parse.MAX_ROWS", 1):
            with self.assertRaisesRegex(CsvLookupError, "more than 1 rows in f.csv"):
                parse_csv_rows("serial\n1\n2\n", key_column="serial", label="f.csv")

    def test_delimiter(self) -> None:
        self.assertEqual(parse_delimiter(None), ";")
        self.assertEqual(parse_delimiter(""), ";")
        self.assertEqual(parse_delimiter("tab"), "\t")
        self.assertEqual(parse_delimiter("\\t"), "\t")
        self.assertEqual(parse_delimiter(","), ",")
        with self.assertRaisesRegex(CsvLookupError, "delimiter"):
            parse_delimiter("ab")


class RowIndexTests(unittest.TestCase):
    def test_exact_first_match_and_duplicates(self) -> None:
        index = RowIndex(_rows("a", "b", "a"), contains=False, case_insensitive=False)
        self.assertEqual(index.find("a").values, {"data": "d-a"})
        self.assertIsNone(index.find("A"))
        self.assertEqual(index.duplicates, 1)

    def test_case_insensitive(self) -> None:
        index = RowIndex(_rows("ABC"), contains=False, case_insensitive=True)
        self.assertIsNotNone(index.find("abc"))

    def test_contains_first_in_file_order(self) -> None:
        longer_first = RowIndex(_rows("1184", "11"), contains=True, case_insensitive=False)
        self.assertEqual(longer_first.find("FOC1184X").key, "1184")
        shorter_first = RowIndex(_rows("11", "1184"), contains=True, case_insensitive=False)
        self.assertEqual(shorter_first.find("FOC1184X").key, "11")

    def test_empty_keys_never_match(self) -> None:
        index = RowIndex(_rows("", "z"), contains=True, case_insensitive=False)
        self.assertIsNone(index.find("abc"))


class ReconcileTests(unittest.TestCase):
    def test_both_sides_exact(self) -> None:
        result = reconcile(_rows("1", "2", "3"), _items("2", "3", "4"))
        self.assertEqual([r.key for r in result.only_in_file], ["1"])
        self.assertEqual([i.value for i in result.only_in_items], ["4"])
        self.assertEqual((result.matched_keys, result.matched_items), (2, 2))
        self.assertEqual((result.file_rows, result.items), (3, 3))

    def test_items_without_value_are_listed_apart(self) -> None:
        result = reconcile(_rows("1"), _items("1", None, "  "))
        self.assertEqual(len(result.items_without_value), 2)
        self.assertEqual(result.only_in_items, ())
        self.assertEqual(result.items, 3)

    def test_rows_without_key_are_counted_not_compared(self) -> None:
        result = reconcile(_rows("", "1"), _items("1"))
        self.assertEqual(result.rows_without_key, 1)
        self.assertEqual(result.only_in_file, ())

    def test_case_and_whitespace(self) -> None:
        sensitive = reconcile(_rows("abc"), _items(" ABC "))
        self.assertEqual(len(sensitive.only_in_file), 1)
        folded = reconcile(_rows("abc"), _items(" ABC "), case_insensitive=True)
        self.assertEqual((folded.only_in_file, folded.only_in_items), ((), ()))

    def test_duplicates_are_counted(self) -> None:
        result = reconcile(_rows("1", "1", "2"), _items("1", "1", "2"))
        self.assertEqual(result.duplicate_keys, 1)
        self.assertEqual(result.duplicate_item_values, 1)
        self.assertEqual(result.only_in_file, ())

    def test_unmatched_duplicate_rows_are_all_listed_in_file_order(self) -> None:
        result = reconcile(_rows("9", "1", "9"), _items("1"))
        self.assertEqual([r.key for r in result.only_in_file], ["9", "9"])

    def test_contains_any_device_matches_row_and_any_row_matches_device(self) -> None:
        result = reconcile(
            _rows("1184", "777", "55"),
            _items("FOC1184X", "FOC999", "ZZ55"),
            contains=True,
        )
        self.assertEqual([r.key for r in result.only_in_file], ["777"])
        self.assertEqual([i.value for i in result.only_in_items], ["FOC999"])
        self.assertEqual((result.matched_keys, result.matched_items), (2, 2))

    def test_contains_counts_items_matching_several_keys_and_short_keys(self) -> None:
        result = reconcile(_rows("1", "12", "FOC"), _items("FOC123"), contains=True)
        self.assertEqual(result.items_matching_several_keys, 1)
        self.assertEqual(result.short_keys, 2)

    def test_short_keys_only_matter_for_contains(self) -> None:
        self.assertEqual(reconcile(_rows("1"), _items("1")).short_keys, 0)

    def test_contains_case_insensitive(self) -> None:
        result = reconcile(_rows("abc"), _items("XABCX"), contains=True, case_insensitive=True)
        self.assertEqual((result.only_in_file, result.only_in_items), ((), ()))

    def test_contains_cap(self) -> None:
        with self.assertRaises(ReconcileTooLargeError):
            reconcile(_rows("1", "2"), _items("1", "2", "3"), contains=True, max_comparisons=5)
        reconcile(_rows("1", "2"), _items("1", "2", "3"), contains=True, max_comparisons=6)

    def test_normalizer_strips_mask_on_both_sides(self) -> None:
        result = reconcile(
            _rows("10.0.0.1/24", "10.0.0.9"),
            _items("10.0.0.1", "10.0.0.9/32"),
            normalizer=normalize_ip_host,
        )
        self.assertEqual((result.only_in_file, result.only_in_items), ((), ()))

    def test_order_follows_the_inputs(self) -> None:
        result = reconcile(_rows("c", "a"), _items("z", "y"))
        self.assertEqual([r.key for r in result.only_in_file], ["c", "a"])
        self.assertEqual([i.value for i in result.only_in_items], ["z", "y"])

    def test_empty_inputs(self) -> None:
        result = reconcile([], [])
        self.assertEqual((result.file_rows, result.items, result.matched_keys), (0, 0, 0))


class MaskOnlyKeyTests(unittest.TestCase):
    """A key that is empty after normalising is a blank key, never a substring of everything."""

    def test_a_mask_only_key_does_not_match_every_address_in_contains_mode(self) -> None:
        for contains in (True, False):
            result = reconcile(
                _rows("/24", "10.0.0.9"),
                _items("10.0.0.1/24", "10.9.9.9/32"),
                contains=contains,
                normalizer=normalize_ip_host,
            )
            self.assertEqual(result.rows_without_key, 1, contains)
            self.assertEqual(result.matched_items, 0, contains)
            self.assertEqual(len(result.only_in_items), 2, contains)
            self.assertEqual([r.key for r in result.only_in_file], ["10.0.0.9"], contains)
            self.assertEqual(result.short_keys, 0, contains)

    def test_a_device_value_that_normalises_to_nothing_is_without_a_value(self) -> None:
        result = reconcile(
            _rows("10.0.0.1"), _items("/32", "10.0.0.1/24"), normalizer=normalize_ip_host
        )
        self.assertEqual(len(result.items_without_value), 1)
        self.assertEqual(result.matched_items, 1)
        self.assertEqual(result.only_in_items, ())


class NormalizerTests(unittest.TestCase):
    def test_ip_host(self) -> None:
        self.assertEqual(normalize_ip_host("10.0.0.1/24"), "10.0.0.1")
        self.assertEqual(normalize_ip_host(" 10.0.0.1 "), "10.0.0.1")
        self.assertEqual(normalize_ip_host("host"), "host")


class PurityTests(unittest.TestCase):
    def test_the_core_imports_neither_steps_nor_the_assistant(self) -> None:
        import ast
        from pathlib import Path

        package = Path(__file__).resolve().parents[2] / "services" / "csv_lookup"
        forbidden = ("workflow_steps", "services.ai_assistant", "core.", "sqlalchemy", "netmiko")
        offenders: list[str] = []
        for path in package.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else []
                )
                offenders += [f"{path.name}: {n}" for n in names if n.startswith(forbidden)]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()

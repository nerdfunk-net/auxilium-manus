"""Tests for services.parsing.structured_document.parse_structured_document."""

from __future__ import annotations

import unittest

from services.parsing.structured_document import parse_structured_document


class ParseStructuredDocumentTests(unittest.TestCase):
    def test_yaml_mapping(self) -> None:
        parsed = parse_structured_document("a: 1\nb: two", fmt="yaml")
        self.assertEqual(parsed, {"a": 1, "b": "two"})

    def test_json_mapping(self) -> None:
        self.assertEqual(parse_structured_document('{"a": 1}', fmt="json"), {"a": 1})

    def test_auto_by_json_extension(self) -> None:
        self.assertEqual(
            parse_structured_document('{"a": 1}', fmt="auto", filename="x.json"), {"a": 1}
        )

    def test_auto_by_yaml_extension(self) -> None:
        self.assertEqual(
            parse_structured_document("a: 1", fmt="auto", filename="dir/x.yaml"), {"a": 1}
        )
        self.assertEqual(parse_structured_document("a: 1", fmt="auto", filename="x.yml"), {"a": 1})

    def test_auto_no_filename_prefers_json_then_yaml(self) -> None:
        self.assertEqual(parse_structured_document('{"a": 1}'), {"a": 1})
        self.assertEqual(parse_structured_document("a: 1"), {"a": 1})

    def test_invalid_yaml_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            parse_structured_document("a: [1, 2", fmt="yaml")
        self.assertIn("invalid YAML", str(ctx.exception))

    def test_explicit_json_on_non_json_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            parse_structured_document("a: 1", fmt="json")
        self.assertIn("invalid JSON", str(ctx.exception))

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(parse_structured_document("", fmt="yaml"))

    def test_unknown_format_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_structured_document("a: 1", fmt="toml")


if __name__ == "__main__":
    unittest.main()

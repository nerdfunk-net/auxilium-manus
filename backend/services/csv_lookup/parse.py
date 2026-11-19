"""Parse a CSV lookup table: one key column, the other columns as values.

Pure code, shared by the ``enrich-attributes`` workflow step and the Ask the Net file comparison
(``doc/AI_TOOL_CHAIN.md`` §61). It imports neither ``workflow_steps`` nor the assistant.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ROWS = 200_000
DEFAULT_DELIMITER = ";"
_DELIMITER_WORDS = {"tab": "\t", "\\t": "\t"}


class CsvLookupError(ValueError):
    """A problem with the file or the options; the message is safe to show (no cell text)."""


class KeyColumnNotFoundError(CsvLookupError):
    """The key column is not in the header. ``columns`` are the file's names (file content, so a
    caller that talks to an AI model shows them only with the user's content opt-in)."""

    def __init__(self, key_column: str, columns: list[str]) -> None:
        super().__init__(f"key column {key_column!r} not found in header {columns}")
        self.key_column = key_column
        self.columns = tuple(columns)


@dataclass(frozen=True)
class CsvRow:
    """One data row: the trimmed key and the other non-empty cells by header name."""

    key: str
    values: dict[str, str]


def parse_delimiter(raw: Any) -> str:
    """A single character, or ``tab``; empty means the default ``;``."""
    text = DEFAULT_DELIMITER if raw is None or raw == "" else str(raw)
    text = _DELIMITER_WORDS.get(text.strip().lower(), text)
    if len(text) != 1:
        raise CsvLookupError("delimiter must be a single character (or 'tab')")
    return text


def parse_csv_rows(
    text: str,
    *,
    key_column: str,
    delimiter: str = DEFAULT_DELIMITER,
    label: str = "the file",
) -> list[CsvRow]:
    """Rows keyed by ``key_column``. The first row is the header; values are trimmed strings.

    An empty cell is left out, so it can never block a real value when the row is merged with
    ``overwrite`` off. Blank lines are skipped. ``label`` names the file in error messages.
    """
    reader = csv.reader(io.StringIO(text.lstrip("﻿"), newline=""), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise CsvLookupError(f"{label} is empty") from None
    except csv.Error as exc:
        raise CsvLookupError(f"invalid CSV: {exc}") from exc

    columns = [name.strip() for name in header]
    if len(set(columns)) != len(columns):
        raise CsvLookupError("duplicate column names in the CSV header")
    if key_column not in columns:
        raise KeyColumnNotFoundError(key_column, columns)
    key_index = columns.index(key_column)

    rows: list[CsvRow] = []
    try:
        for record in reader:
            if not any(cell.strip() for cell in record):
                continue  # blank line
            if len(rows) >= MAX_ROWS:
                raise CsvLookupError(f"more than {MAX_ROWS} rows in {label}")
            cells = [cell.strip() for cell in record]
            cells += [""] * (len(columns) - len(cells))
            values = {
                name: cells[i]
                for i, name in enumerate(columns)
                if i != key_index and name and cells[i]
            }
            rows.append(CsvRow(key=cells[key_index], values=values))
    except csv.Error as exc:
        raise CsvLookupError(f"invalid CSV: {exc}") from exc
    return rows

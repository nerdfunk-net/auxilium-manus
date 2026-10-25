"""Read device rows from a CSV file (one dict per data line, keyed by header).

Port of the app's ``services/git/csv_device_reader.py`` (the agent must not import the backend).
Problems (bad encoding, ragged lines, ...) are returned as strings instead of raised, so one
broken file does not hide the others.
"""

from __future__ import annotations

import csv
from pathlib import Path

MAX_CSV_BYTES = 10 * 1024 * 1024
ALLOWED_DELIMITERS: tuple[str, ...] = (";", ",", "\t", "|")
_MAX_RAGGED_WARNINGS = 5


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def read_csv_rows(path: Path, delimiter: str) -> tuple[list[dict[str, str]], list[str]]:
    """Return ``(rows, problems)`` for ``path``.

    The first non-blank line is the header. Cells are stripped; fully blank lines are skipped.
    A line whose field count differs from the header is still read (missing cells become
    ``""``, extra cells are dropped) but reported, because a missing delimiter shifts values
    into the wrong columns.
    """
    name = path.name
    try:
        if path.stat().st_size > MAX_CSV_BYTES:
            return [], [f"{name}: file too large (limit {MAX_CSV_BYTES // (1024 * 1024)} MB)"]
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh, delimiter=delimiter)
            lines = [(reader.line_num, cells) for cells in reader]
    except UnicodeDecodeError:
        return [], [f"{name}: not valid UTF-8 text"]
    except (csv.Error, OSError) as exc:
        return [], [f"{name}: cannot be read as CSV ({type(exc).__name__})"]
    return _rows_from_lines(name, lines)


def _rows_from_lines(
    name: str, lines: list[tuple[int, list[str]]]
) -> tuple[list[dict[str, str]], list[str]]:
    header: list[str] | None = None
    rows: list[dict[str, str]] = []
    ragged: list[str] = []
    problems: list[str] = []

    for line_no, cells in lines:
        stripped = [cell.strip() for cell in cells]
        if not any(stripped):
            continue
        if header is None:
            header = stripped
            if len(set(header)) != len(header):
                problems.append(f"{name}: duplicate column names in the header")
            continue
        if len(stripped) != len(header):
            ragged.append(
                f"{name}: line {line_no} has {len(stripped)} "
                f"{_plural(len(stripped), 'field', 'fields')}, expected {len(header)}"
            )
        padded = (stripped + [""] * len(header))[: len(header)]
        rows.append(dict(zip(header, padded, strict=True)))

    if header is None:
        return [], [f"{name}: file is empty (no header line)"]

    problems.extend(ragged[:_MAX_RAGGED_WARNINGS])
    hidden = len(ragged) - _MAX_RAGGED_WARNINGS
    if hidden > 0:
        problems.append(f"{name}: {hidden} more lines with a wrong number of fields")
    return rows, problems

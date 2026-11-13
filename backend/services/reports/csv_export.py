"""CSV export of a snapshot: the raw section data that sits next to the PDF.

One section gives one CSV file, several give a zip with one CSV per section (named after the
section id). A section that failed has no data and is left out. Cells come from device data, so
a text cell that a spreadsheet would read as a formula (it starts with ``=``, ``+``, ``-``,
``@``, a tab or a carriage return) gets a leading apostrophe. Numbers are written as they are.
The files start with a UTF-8 byte order mark so that Excel reads umlauts correctly.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from typing import Any

from models.report_definitions import SnapshotContent, SnapshotSection
from models.reports import QueryResult
from services.reports.report_mailer import pdf_filename

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_BOM = "﻿"
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
ZIP_MEDIA_TYPE = "application/zip"


class NothingToExportError(ValueError):
    """The snapshot has no section with data (every section failed)."""


@dataclass(frozen=True)
class CsvExport:
    filename: str
    media_type: str
    data: bytes


def snapshot_csv(content: SnapshotContent) -> CsvExport:
    """The snapshot's data as one CSV file, or a zip of CSV files when it has several sections."""
    sections = [s for s in content.sections if s.status == "ok" and s.result is not None]
    if not sections:
        raise NothingToExportError("The snapshot has no section with data to export.")
    stem = pdf_filename(content.name).removesuffix(".pdf")
    if len(sections) == 1:
        return CsvExport(f"{stem}.csv", CSV_MEDIA_TYPE, _csv_bytes(_result(sections[0])))
    return CsvExport(f"{stem}.zip", ZIP_MEDIA_TYPE, _zip_bytes(sections))


def _zip_bytes(sections: list[SnapshotSection]) -> bytes:
    buffer = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, section in enumerate(sections, start=1):
            archive.writestr(_member_name(section, index, used), _csv_bytes(_result(section)))
    return buffer.getvalue()


def _member_name(section: SnapshotSection, index: int, used: set[str]) -> str:
    stem = _UNSAFE_NAME.sub("-", section.section.id).strip("-.") or f"section-{index}"
    name = stem
    while f"{name}.csv" in used:  # ids are unique in a report; this only guards odd data
        name = f"{stem}-{index}"
        index += 1
    used.add(f"{name}.csv")
    return f"{name}.csv"


def _result(section: SnapshotSection) -> QueryResult:
    if section.result is None:
        raise NothingToExportError(f"Section {section.section.id!r} has no data.")
    return section.result


def _csv_bytes(result: QueryResult) -> bytes:
    out = io.StringIO()
    out.write(_BOM)
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([_cell(column.label) for column in result.columns])
    for row in result.rows:
        writer.writerow([_cell(value) for value in row])
    return out.getvalue().encode("utf-8")


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value

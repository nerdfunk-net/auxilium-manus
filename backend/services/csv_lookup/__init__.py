"""Shared CSV lookup core: parsing, first-match index and two-sided reconcile (no I/O)."""

from services.csv_lookup.match import (
    MAX_COMPARISONS,
    MAX_MATCH_PAIRS,
    MatchedPair,
    ReconcileTooLargeError,
    Reconciliation,
    RowIndex,
    ValueItem,
    normalize,
    normalize_ip_host,
    reconcile,
)
from services.csv_lookup.parse import (
    DEFAULT_DELIMITER,
    MAX_FILE_BYTES,
    MAX_ROWS,
    CsvLookupError,
    CsvRow,
    KeyColumnNotFoundError,
    parse_csv_rows,
    parse_delimiter,
)

__all__ = [
    "DEFAULT_DELIMITER",
    "MAX_COMPARISONS",
    "MAX_FILE_BYTES",
    "MAX_MATCH_PAIRS",
    "MAX_ROWS",
    "CsvLookupError",
    "CsvRow",
    "KeyColumnNotFoundError",
    "MatchedPair",
    "ReconcileTooLargeError",
    "Reconciliation",
    "RowIndex",
    "ValueItem",
    "normalize",
    "normalize_ip_host",
    "parse_csv_rows",
    "parse_delimiter",
    "reconcile",
]

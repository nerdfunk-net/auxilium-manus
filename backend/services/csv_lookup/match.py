"""Matching a CSV lookup table against values: the step's first-match index and a two-sided diff.

Pure code (no I/O). ``RowIndex`` answers "which row belongs to this device" for the
``enrich-attributes`` step; ``reconcile`` answers "which file keys have no value and which values
have no file key" for the Ask the Net comparison. ``contains`` means the *value contains the key*.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from services.csv_lookup.parse import CsvLookupError, CsvRow

# ``contains`` compares every distinct key with every distinct value.
MAX_COMPARISONS = 5_000_000
SHORT_KEY_LENGTH = 2
# Pairs (file row, item) kept for the "in both" list; the count stays exact beyond it.
MAX_MATCH_PAIRS = 200_000


class ReconcileTooLargeError(CsvLookupError):
    """``contains`` would need more comparisons than ``MAX_COMPARISONS``."""


@dataclass(frozen=True)
class ValueItem:
    """One thing to compare against the file keys (for example a device and its serial)."""

    id: str
    value: str | None
    info: Mapping[str, str] = field(default_factory=dict)


def normalize(value: str, *, case_insensitive: bool) -> str:
    return value.casefold() if case_insensitive else value


def normalize_ip_host(value: str) -> str:
    """``10.0.0.1/24`` -> ``10.0.0.1`` (Nautobot's primary address has a mask, a file may not)."""
    return value.strip().split("/", 1)[0].strip()


class RowIndex:
    """First-match lookup: dict for ``match``, ordered scan for ``contains``."""

    def __init__(self, rows: Sequence[CsvRow], *, contains: bool, case_insensitive: bool) -> None:
        self._contains = contains
        self._ci = case_insensitive
        self._ordered: list[tuple[str, CsvRow]] = []
        self._exact: dict[str, CsvRow] = {}
        self.duplicates = 0
        for row in rows:
            if not row.key:
                continue
            key = normalize(row.key, case_insensitive=case_insensitive)
            self._ordered.append((key, row))
            if key in self._exact:
                self.duplicates += 1
            else:
                self._exact[key] = row

    def find(self, value: str) -> CsvRow | None:
        """The first matching row in file order (``contains`` stops at the first hit)."""
        needle = normalize(value, case_insensitive=self._ci)
        if not self._contains:
            return self._exact.get(needle)
        return next((row for key, row in self._ordered if key in needle), None)


@dataclass(frozen=True)
class MatchedPair:
    """A file row and an item that match each other (one pair per row and item)."""

    row: CsvRow
    item: ValueItem


@dataclass(frozen=True)
class Reconciliation:
    file_rows: int
    rows_without_key: int
    items: int
    only_in_file: tuple[CsvRow, ...]
    only_in_items: tuple[ValueItem, ...]
    items_without_value: tuple[ValueItem, ...]
    matched_keys: int
    matched_items: int
    duplicate_keys: int
    duplicate_item_values: int
    items_matching_several_keys: int
    short_keys: int
    # Every (file row, item) pair that matches, in item order and, per item, in file order; at most
    # ``MAX_MATCH_PAIRS`` of them (``match_pairs`` is the exact number).
    matches: tuple[MatchedPair, ...] = ()
    match_pairs: int = 0


def reconcile(
    rows: Sequence[CsvRow],
    items: Sequence[ValueItem],
    *,
    contains: bool = False,
    case_insensitive: bool = False,
    normalizer: Callable[[str], str] | None = None,
    max_comparisons: int = MAX_COMPARISONS,
    max_match_pairs: int = MAX_MATCH_PAIRS,
) -> Reconciliation:
    """Both directions: a row is matched if *any* item matches it, an item if *any* row does.

    Rows with an empty key and items with an empty value are not compared (they are counted and
    listed apart). Order follows the inputs. Raises ``ReconcileTooLargeError`` when ``contains``
    would need more than ``max_comparisons`` key/value comparisons.
    """

    def norm(text: str) -> str:
        prepared = text.strip()
        if normalizer is not None:
            prepared = normalizer(prepared)
        return normalize(prepared, case_insensitive=case_insensitive)

    # A key (or value) that is empty after normalising, for example "/24" once the mask is
    # stripped, is blank: "" is a substring of everything and must never count as a match.
    keyed = [(key, row) for row in rows if (key := norm(row.key))]
    rows_without_key = len(rows) - len(keyed)
    valued: list[tuple[str, ValueItem]] = []
    without_value: list[ValueItem] = []
    for item in items:
        value = norm(item.value) if item.value is not None else ""
        if value:
            valued.append((value, item))
        else:
            without_value.append(item)

    keys = {key for key, _ in keyed}
    values = {value for value, _ in valued}
    duplicate_keys = len(keyed) - len(keys)
    duplicate_item_values = len(valued) - len(values)

    rows_by_key: dict[str, list[CsvRow]] = {}
    for key, row in keyed:
        rows_by_key.setdefault(key, []).append(row)
    ordered_keys = list(rows_by_key)

    if contains and len(keys) * len(values) > max_comparisons:
        raise ReconcileTooLargeError(
            f"'contains' would need {len(keys) * len(values)} comparisons "
            f"(limit {max_comparisons}); use 'match' or narrow the devices"
        )
    short_keys = sum(1 for key in keys if len(key) <= SHORT_KEY_LENGTH) if contains else 0

    matched_key_set: set[str] = set()
    matched_value_set: set[str] = set()
    several_values: set[str] = set()
    pairs: list[MatchedPair] = []
    pair_count = 0
    hits_by_value: dict[str, list[str]] = {}
    for value, item in valued:
        if value not in hits_by_value:
            if contains:
                hits_by_value[value] = [key for key in ordered_keys if key in value]
            else:
                hits_by_value[value] = [value] if value in rows_by_key else []
        hits = hits_by_value[value]
        if not hits:
            continue
        matched_value_set.add(value)
        matched_key_set.update(hits)
        if len(hits) > 1:
            several_values.add(value)
        for key in hits:
            for row in rows_by_key[key]:
                pair_count += 1
                if len(pairs) < max_match_pairs:
                    pairs.append(MatchedPair(row=row, item=item))

    return Reconciliation(
        file_rows=len(rows),
        rows_without_key=rows_without_key,
        items=len(items),
        only_in_file=tuple(row for key, row in keyed if key not in matched_key_set),
        only_in_items=tuple(item for value, item in valued if value not in matched_value_set),
        items_without_value=tuple(without_value),
        matched_keys=len(matched_key_set),
        matched_items=sum(1 for value, _ in valued if value in matched_value_set),
        duplicate_keys=duplicate_keys,
        duplicate_item_values=duplicate_item_values,
        items_matching_several_keys=sum(1 for value, _ in valued if value in several_values),
        short_keys=short_keys,
        matches=tuple(pairs),
        match_pairs=pair_count,
    )

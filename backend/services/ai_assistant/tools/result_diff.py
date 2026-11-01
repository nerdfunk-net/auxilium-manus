"""Pure table comparison for ``diff_results`` (doc/AI_TOOL_CHAIN.md §12.3).

No I/O, no rights, no redaction: two lists of rows in, the differences out. With a ``key`` (the
columns that identify a row) rows are matched across the tables and a changed row lists the fields
that differ. Without one, whole rows are compared as a multiset (a changed row is then one removed
plus one added). Nothing here mutates its input.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_MISSING = "(missing)"


class DiffError(ValueError):
    """The tables cannot be compared as asked; the message is written for the model."""


@dataclass(frozen=True)
class DiffResult:
    rows: list[dict[str, Any]]
    counts: dict[str, int]


def get_path(row: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    """A value by dot path (``Interface.name``); ``(False, None)`` when any step is absent."""
    node: Any = row
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return False, None
        node = node[part]
    return True, node


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _without(row: Mapping[str, Any], ignore: frozenset[str]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in ignore}


def _key_of(row: Mapping[str, Any], key: Sequence[str]) -> str:
    return _canon([get_path(row, path)[1] for path in key])


def _index(
    rows: Iterable[Mapping[str, Any]], key: Sequence[str], side: str
) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        for path in key:
            if not get_path(row, path)[0]:
                # An absent column and a null value must not become the same key.
                raise DiffError(
                    f"A row in table {side} has no column '{path}', so it cannot be matched. "
                    "Choose key columns that every row has."
                )
        k = _key_of(row, key)
        if k in indexed:
            raise DiffError(
                f"The key {list(key)} is not unique in table {side}: more than one row has "
                f"{k}. Add a column to key that tells those rows apart."
            )
        indexed[k] = row
    return indexed


def _key_dict(row: Mapping[str, Any], key: Sequence[str]) -> dict[str, Any]:
    return {path: get_path(row, path)[1] for path in key}


def _differences(
    a: Mapping[str, Any], b: Mapping[str, Any], ignore: frozenset[str]
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for field in [*a, *(f for f in b if f not in a)]:
        if field in ignore:
            continue
        left, right = a.get(field, _MISSING), b.get(field, _MISSING)
        if _canon(left) != _canon(right):
            out[field] = {"a": left, "b": right}
    return out


def diff_tables(
    a: Sequence[Mapping[str, Any]],
    b: Sequence[Mapping[str, Any]],
    *,
    key: Sequence[str] | None,
    ignore: frozenset[str],
) -> DiffResult:
    if key:
        return _diff_keyed(a, b, key, ignore)
    return _diff_unkeyed(a, b, ignore)


def _diff_keyed(
    a: Sequence[Mapping[str, Any]],
    b: Sequence[Mapping[str, Any]],
    key: Sequence[str],
    ignore: frozenset[str],
) -> DiffResult:
    for path in key:
        if not any(get_path(row, path)[0] for row in (*a, *b)):
            raise DiffError(f"No row in either table has the key column '{path}'.")
    left, right = _index(a, key, "A"), _index(b, key, "B")
    rows: list[dict[str, Any]] = []
    counts = {"removed": 0, "changed": 0, "added": 0, "unchanged": 0}
    for k, row in left.items():
        other = right.get(k)
        if other is None:
            rows.append({"change": "removed", "row": dict(row)})
            counts["removed"] += 1
            continue
        diff = _differences(row, other, ignore)
        if diff:
            rows.append({"change": "changed", "key": _key_dict(row, key), "differences": diff})
            counts["changed"] += 1
        else:
            counts["unchanged"] += 1
    for k, row in right.items():
        if k not in left:
            rows.append({"change": "added", "row": dict(row)})
            counts["added"] += 1
    return DiffResult(rows=rows, counts=counts)


def _diff_unkeyed(
    a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]], ignore: frozenset[str]
) -> DiffResult:
    first: dict[str, dict[str, Any]] = {}
    left: Counter[str] = Counter()
    right: Counter[str] = Counter()
    for table, counter in ((a, left), (b, right)):
        for row in table:
            kept = _without(row, ignore)
            canon = _canon(kept)
            first.setdefault(canon, kept)
            counter[canon] += 1
    rows: list[dict[str, Any]] = []
    counts = {"removed": 0, "changed": 0, "added": 0, "unchanged": 0}
    for canon, n in left.items():
        extra = n - right.get(canon, 0)
        counts["unchanged"] += min(n, right.get(canon, 0))
        if extra > 0:
            counts["removed"] += extra
            rows.append({"change": "removed", "row": first[canon], **_count(extra)})
    for canon, n in right.items():
        extra = n - left.get(canon, 0)
        if extra > 0:
            counts["added"] += extra
            rows.append({"change": "added", "row": first[canon], **_count(extra)})
    return DiffResult(rows=rows, counts=counts)


def _count(n: int) -> dict[str, int]:
    return {"count": n} if n > 1 else {}

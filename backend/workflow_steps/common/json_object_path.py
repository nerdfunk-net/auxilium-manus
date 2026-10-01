"""Get/set a value at a dotted path inside a plain JSON-like document.

Distinct from ``attribute_write.py``/``attribute_merge.py``, which operate on
``DeviceContext.attribute_bags`` and understand reserved bag names, sealed
secrets, and Capability bookkeeping. This module knows nothing about
``DeviceContext`` — it walks a raw ``dict``/``list`` structure such as a
Nautobot device's ``local_config_context_data``.

Path syntax: ``.``-separated segments. A segment is treated as a **list
index** only when the current cursor is a ``list`` and the segment parses as
a non-negative integer (e.g. ``credentials.0.password``); otherwise it is a
dict key. The bracket form ``<key>[<n>]`` (``credentials[0].password``) is the same
as ``credentials.0.password``, matching ``attribute_path.py``.

A segment may also be a **filter** ``<key>[<field>=<value>]`` (e.g.
``tacacs[address=1.2.3.4].key``): it selects the first item of the list at
``<key>`` whose ``<field>`` stringifies to ``<value>``, the same grammar
``services/workflow_context/attribute_path.py`` uses for reads. ``<field>``
may itself be a dotted sub-path and must resolve to a scalar. Dots inside the
brackets do not split the path, so an IP address works as a value.

Lists are never extended: a numeric index must already exist, and a filter
that matches nothing raises ``ValueError`` on write (``None`` on read).
"""

from __future__ import annotations

import re
from typing import Any

# Mirrors attribute_path._FILTER_SEGMENT_RE (kept local so this module stays
# free of DeviceContext imports).
_FILTER_SEGMENT_RE = re.compile(r"^(?P<key>[^\[\]]+)\[(?P<field>[^\[\]=]+)=(?P<value>[^\[\]]*)\]$")
# ... and attribute_path._INDEX_SEGMENT_RE: digits only, so it can't collide with the filter.
_INDEX_SEGMENT_RE = re.compile(r"^(?P<key>[^\[\]]+)\[(?P<index>\d+)\]$")


class _ListSegment:
    """A ``key[field=value]`` filter or ``key[n]`` index segment."""

    def __init__(self, key: str, *, field: str | None = None, value: str = "", index: int = 0):
        self.key = key
        self.field = field
        self.value = value
        self.index = index

    def find(self, items: Any) -> int | None:
        """Index in *items* this segment selects, or ``None``."""
        if not isinstance(items, list):
            return None
        if self.field is None:
            return self.index if self.index < len(items) else None
        return _find_filtered_index(items, self.field, self.value)

    def describe(self) -> str:
        return f"index {self.index}" if self.field is None else f"{self.field}={self.value}"


def _list_segment(segment: str) -> _ListSegment | None:
    match = _FILTER_SEGMENT_RE.match(segment)
    if match:
        return _ListSegment(
            match.group("key"), field=match.group("field"), value=match.group("value")
        )
    match = _INDEX_SEGMENT_RE.match(segment)
    if match:
        return _ListSegment(match.group("key"), index=int(match.group("index")))
    return None


def _split_path(path: str) -> list[str]:
    """Split on ``.`` but not inside a ``[...]`` filter."""
    segments: list[str] = []
    current: list[str] = []
    depth = 0
    for char in path.strip():
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(0, depth - 1)
        elif char == "." and depth == 0:
            segments.append("".join(current))
            current = []
            continue
        current.append(char)
    segments.append("".join(current))
    cleaned = [segment for segment in segments if segment]
    if not cleaned:
        raise ValueError("path must not be empty")
    return cleaned


def top_level_key(path: str) -> str:
    """The root-document key a path starts at, with any ``[field=value]``
    filter or ``[n]`` index stripped (``tacacs[address=1.2.3.4].key`` -> ``tacacs``)."""
    first = _split_path(path)[0]
    selector = _list_segment(first)
    return selector.key if selector else first


def _find_filtered_index(items: Any, field: str, value: str) -> int | None:
    """Index of the first dict in *items* whose ``field`` stringifies to *value*."""
    if not isinstance(items, list):
        return None
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        candidate = get_at_path(item, field)
        if candidate is None or isinstance(candidate, (dict, list)):
            continue
        if str(candidate) == value:
            return index
    return None


def get_at_path(document: Any, path: str) -> Any:
    """Return the value at *path*.

    Returns ``None`` when any segment is absent, a numeric segment is out of
    range, or the path runs past a scalar leaf — reads fail soft.
    """
    cursor: Any = document
    for segment in _split_path(path):
        if isinstance(cursor, list):
            if not segment.isdigit():
                return None
            index = int(segment)
            if index >= len(cursor):
                return None
            cursor = cursor[index]
        elif isinstance(cursor, dict):
            selector = _list_segment(segment)
            if selector:
                items = cursor.get(selector.key)
                index = selector.find(items)
                if not isinstance(items, list) or index is None:
                    return None
                cursor = items[index]
                continue
            if segment not in cursor:
                return None
            cursor = cursor[segment]
        else:
            return None
    return cursor


def _step_down(value: Any, *, path: str) -> dict[str, Any] | list[Any]:
    """Return a mutable copy of *value* to descend into while building a
    ``set_at_path`` write, creating an empty ``dict`` when it's absent/empty.

    Raises ``ValueError`` rather than silently discarding an existing
    non-empty scalar the path would otherwise overwrite with a container.
    """
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    if value in (None, ""):
        return {}
    raise ValueError(
        f"path {path!r}: cannot create a nested value under an existing non-empty scalar"
    )


def _locate_filtered(cursor: dict[str, Any], segment: str, *, path: str) -> tuple[list[Any], int]:
    """Copy the list a filter/index segment targets into *cursor* and return it
    with the index of the selected item. Raises ``ValueError`` when there is no
    list at the key or nothing is selected (lists are never extended)."""
    selector = _list_segment(segment)
    assert selector is not None  # noqa: S101  # callers check the segment first
    existing = cursor.get(selector.key)
    if not isinstance(existing, list):
        raise ValueError(
            f"path {path!r}: {selector.key!r} is not a list, cannot select by {selector.describe()}"
        )
    index = selector.find(existing)
    if index is None:
        if selector.field is None:
            raise ValueError(
                f"path {path!r}: index {selector.index} out of range "
                f"for list of length {len(existing)}"
            )
        raise ValueError(f"path {path!r}: no item in {selector.key!r} where {selector.describe()}")
    items = list(existing)
    cursor[selector.key] = items
    return items, index


def _descend_filter(
    cursor: dict[str, Any], segment: str, *, path: str
) -> dict[str, Any] | list[Any]:
    items, index = _locate_filtered(cursor, segment, path=path)
    nxt = _step_down(items[index], path=path)
    items[index] = nxt
    return nxt


def set_at_path(document: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    """Return a copy of *document* with *value* set at *path*.

    Missing dict keys are created as needed. Raises ``ValueError`` when a
    numeric segment is out of range for an existing list (lists are never
    extended), or when the walk would have to step through an existing
    non-empty scalar to keep going.
    """
    segments = _split_path(path)
    root: dict[str, Any] = dict(document)
    cursor: Any = root
    for segment in segments[:-1]:
        if isinstance(cursor, dict) and _list_segment(segment):
            cursor = _descend_filter(cursor, segment, path=path)
            continue
        if isinstance(cursor, list):
            if not segment.isdigit():
                raise ValueError(f"path {path!r}: {segment!r} is not a valid list index")
            index = int(segment)
            if index >= len(cursor):
                raise ValueError(
                    f"path {path!r}: index {index} out of range for list of length {len(cursor)}"
                )
            nxt = _step_down(cursor[index], path=path)
            cursor[index] = nxt
            cursor = nxt
        elif isinstance(cursor, dict):
            nxt = _step_down(cursor.get(segment), path=path)
            cursor[segment] = nxt
            cursor = nxt
        else:
            raise ValueError(f"path {path!r}: cannot traverse into a non-container value")

    leaf = segments[-1]
    if isinstance(cursor, dict) and _list_segment(leaf):
        items, index = _locate_filtered(cursor, leaf, path=path)
        items[index] = value
    elif isinstance(cursor, list):
        if not leaf.isdigit():
            raise ValueError(f"path {path!r}: {leaf!r} is not a valid list index")
        index = int(leaf)
        if index >= len(cursor):
            raise ValueError(
                f"path {path!r}: index {index} out of range for list of length {len(cursor)}"
            )
        cursor[index] = value
    elif isinstance(cursor, dict):
        cursor[leaf] = value
    else:
        raise ValueError(f"path {path!r}: cannot traverse into a non-container value")

    return root

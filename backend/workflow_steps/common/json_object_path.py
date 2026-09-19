"""Get/set a value at a dotted path inside a plain JSON-like document.

Distinct from ``attribute_write.py``/``attribute_merge.py``, which operate on
``DeviceContext.attribute_bags`` and understand reserved bag names, sealed
secrets, and Capability bookkeeping. This module knows nothing about
``DeviceContext`` — it walks a raw ``dict``/``list`` structure such as a
Nautobot device's ``local_config_context_data``.

Path syntax: ``.``-separated segments. A segment is treated as a **list
index** only when the current cursor is a ``list`` and the segment parses as
a non-negative integer (e.g. ``credentials.0.password``); otherwise it is a
dict key. There is no ``[field=value]`` filter support and no list
extension — the target index must already exist.
"""

from __future__ import annotations

from typing import Any


def _split_path(path: str) -> list[str]:
    segments = [segment for segment in path.strip().split(".") if segment]
    if not segments:
        raise ValueError("path must not be empty")
    return segments


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
    if isinstance(cursor, list):
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

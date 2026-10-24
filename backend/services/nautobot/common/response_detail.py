"""Turn a Nautobot 400 validation body into a short, safe sentence for an exception message.

Response text normally stays out of exception messages because a step persists them on the
device and in the run result (C7-03). The one deliberate exception is a REST 400 whose body is
structured validation JSON (``{"__all__": ["..."], "name": ["..."]}``): it says what the author
must fix. Everything else (5xx, HTML, GraphQL) keeps the payload-free message.

Pure functions, no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

MAX_DETAIL_CHARS = 300
_MAX_ENTRIES = 5
# Keys that describe the object as a whole, so no "field:" prefix is shown.
_WHOLE_OBJECT_KEYS = frozenset({"__all__", "non_field_errors", "detail"})
_TAGS = re.compile(r"<[^>]+>")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def _clean(text: str) -> str:
    stripped = _CONTROL.sub(" ", _TAGS.sub(" ", text))
    return " ".join(stripped.split())


def _entries(node: Any, path: str) -> Iterator[str]:
    """Yield ``"path: message"`` for every string leaf of a validation body."""
    if isinstance(node, str):
        message = _clean(node)
        if message:
            yield f"{path}: {message}" if path else message
    elif isinstance(node, list):
        for item in node:
            yield from _entries(item, path)
    elif isinstance(node, dict):
        for key, value in node.items():
            name = str(key)
            child = path if name in _WHOLE_OBJECT_KEYS else f"{path}.{name}" if path else name
            yield from _entries(value, child)


def validation_fields(body: Any) -> tuple[str, ...]:
    """Top-level keys of a validation body that carry a message (``__all__`` for a list body).

    Structured facts about which field Nautobot rejected, so callers need not parse the text.
    """
    if isinstance(body, list):
        return ("__all__",) if any(True for _ in _entries(body, "")) else ()
    if not isinstance(body, dict):
        return ()
    return tuple(str(key) for key, value in body.items() if any(True for _ in _entries(value, "")))


def validation_detail(body: Any) -> str | None:
    """Flatten a structured validation body; ``None`` when it holds no usable message."""
    if not isinstance(body, (dict, list)):
        return None
    parts: list[str] = []
    for entry in _entries(body, ""):
        parts.append(entry)
        if len(parts) >= _MAX_ENTRIES:
            break
    if not parts:
        return None
    text = "; ".join(parts)
    if len(text) > MAX_DETAIL_CHARS:
        return text[: MAX_DETAIL_CHARS - 1].rstrip() + "…"
    return text

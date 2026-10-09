"""Whitelisted attribute updates for repositories (Q6)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def apply_updates(obj: Any, values: Mapping[str, object], allowed: frozenset[str]) -> None:
    """Set ``values`` on ``obj``; refuse any key outside ``allowed``.

    Replaces ``if hasattr(obj, key): setattr(...)``, which silently accepts any attribute
    (including primary keys and relationship names) and silently drops typos.
    """
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"{type(obj).__name__}: fields not updatable: {', '.join(unknown)}")
    for key, value in values.items():
        setattr(obj, key, value)

"""repositories.updates.apply_updates whitelists attributes (Q6)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from repositories.updates import apply_updates


def test_sets_allowed_keys() -> None:
    obj = SimpleNamespace(a=1, b=2)
    apply_updates(obj, {"a": 10}, frozenset({"a", "b"}))
    assert (obj.a, obj.b) == (10, 2)


def test_unknown_key_raises_and_changes_nothing() -> None:
    obj = SimpleNamespace(a=1, id=7)
    with pytest.raises(ValueError, match="id"):
        apply_updates(obj, {"a": 10, "id": 99}, frozenset({"a"}))
    assert (obj.a, obj.id) == (1, 7)


def test_empty_mapping_is_a_noop() -> None:
    obj = SimpleNamespace(a=1)
    apply_updates(obj, {}, frozenset())
    assert obj.a == 1

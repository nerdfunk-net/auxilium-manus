"""Field-name and rendered-path rules for Secret Manager requests (SM5)."""

from __future__ import annotations

import pytest

from services.secret_manager.validation import validate_field, validate_kv_path


@pytest.mark.parametrize(
    "field",
    ["", ".", "..", "../x", "a/b", "a?b", "a#b", "a%2fb", ".hidden", "-x", "x" * 256],
)
def test_field_rejects_dotdot_slash_query(field: str) -> None:
    with pytest.raises(ValueError):
        validate_field(field)


@pytest.mark.parametrize("field", ["key", "tacacs_key", "api-token", "a.b", "_x", "K1"])
def test_field_accepts_normal_names(field: str) -> None:
    assert validate_field(field) == field


@pytest.mark.parametrize(
    "path", ["", "/abs", "a//b", "a/../b", "a/./b", "a/", "a#b", "a%2fb", "a?x=1", "a\\b", ".."]
)
def test_path_rejects_hash_percent_dotdot_empty_segment(path: str) -> None:
    with pytest.raises(ValueError):
        validate_kv_path(path)


@pytest.mark.parametrize(
    "path",
    ["network/sw-1/tacacs", "network/sw 1/tacacs", "net/dev@lab.local/key", "a/b_c/d.e", "x=1/y+2"],
)
def test_path_accepts_device_paths(path: str) -> None:
    assert validate_kv_path(path) == path

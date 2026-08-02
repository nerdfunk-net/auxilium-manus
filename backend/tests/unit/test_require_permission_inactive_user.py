"""require_permission (and its siblings) must reject deactivated users even
when get_current_user is not in the dependency chain — see FABLE-ANALYSIS.md §4.3."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from core.auth import (
    require_all_permissions,
    require_any_permission,
    require_permission,
    require_role,
)
from core.models.users import User


def _user(is_active: bool) -> User:
    user = User(username="alice", password_hash="hash", is_active=is_active)
    user.id = 1
    return user


@pytest.mark.parametrize(
    "checker_factory",
    [
        lambda: require_permission("workflows", "read"),
        lambda: require_any_permission([("workflows", "read")]),
        lambda: require_all_permissions([("workflows", "read")]),
        lambda: require_role("admin"),
    ],
)
def test_rejects_deactivated_user_even_with_valid_permission(monkeypatch, checker_factory) -> None:
    monkeypatch.setattr("core.auth.RBACService.has_permission", lambda self, *a: True)
    monkeypatch.setattr("core.auth.RBACService.check_any_permission", lambda self, *a: True)
    monkeypatch.setattr("core.auth.RBACService.check_all_permissions", lambda self, *a: True)
    monkeypatch.setattr("core.auth.RBACService.has_role", lambda self, *a: True)
    monkeypatch.setattr(
        "core.auth.UserRepository.get_by_id",
        lambda self, user_id: _user(is_active=False),
    )

    checker = checker_factory()
    with pytest.raises(HTTPException) as exc_info:
        checker({"user_id": 1}, MagicMock())

    assert exc_info.value.status_code == 401

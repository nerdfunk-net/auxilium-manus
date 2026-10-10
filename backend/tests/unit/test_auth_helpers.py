"""Pins the contract of the shared auth doubles (T3)."""

from __future__ import annotations

from _auth_helpers import make_auth_db, make_user, token_payload

from core.auth import _load_active_user


def test_token_payload_passes_load_active_user() -> None:
    user = _load_active_user(token_payload(), make_auth_db())
    assert user.id == 1


def test_make_user_defaults() -> None:
    user = make_user()
    assert user.is_active is True
    assert user.token_version == 0
    assert user.must_change_password is False

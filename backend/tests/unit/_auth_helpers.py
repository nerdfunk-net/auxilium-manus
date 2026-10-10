"""Shared auth doubles for router/dependency tests (T3).

`core.auth._load_active_user` requires `tv` (== user.token_version) and `sid_iat`
(within SESSION_MAX_AGE_HOURS) on every token. These helpers produce a payload and a
DB double that satisfy that check so tests exercise the real guard instead of
bypassing it.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

from core.models.users import User


def token_payload(
    user_id: int = 1, *, tv: int = 0, username: str = "tester", **extra: Any
) -> dict[str, Any]:
    """A valid verify_token payload.

    Wrap it in a zero-arg lambda when overriding ``verify_token``
    (``lambda: token_payload()``): assigned bare, FastAPI would treat its parameters as
    query params.
    """
    now = int(time.time())
    return {"sub": username, "user_id": user_id, "tv": tv, "sid_iat": now, "iat": now, **extra}


def make_user(user_id: int = 1, *, username: str = "tester", token_version: int = 0) -> User:
    user = User(username=username, password_hash="hash", is_active=True)
    user.id = user_id
    user.token_version = token_version
    user.must_change_password = False
    return user


def make_auth_db(user: User | None = None) -> MagicMock:
    """A Session double whose ``db.get(User, id)`` returns an active user with token_version 0.

    ``UserRepository.get_by_id`` is ``self.db.get(User, user_id)``, so this is all
    ``_load_active_user`` touches. Everything else stays a plain MagicMock.

    The user is returned for *any* id, so when the token's ``user_id`` is not 1 pass a
    matching ``make_user(user_id, ...)`` — otherwise the permission gate runs as user 1.
    """
    db = MagicMock()
    db.get.return_value = user or make_user()
    return db

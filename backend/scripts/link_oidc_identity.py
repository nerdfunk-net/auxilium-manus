#!/usr/bin/env python3
"""Bind an existing local user to an IdP identity.

    python scripts/link_oidc_identity.py <username> <provider_id> <subject>

An OIDC login only ever matches on (oidc_provider, oidc_subject) -- never on username -- so
this is the only way to let an existing local account sign in through SSO. Run it deliberately.
Existing sessions of the user are ended (token_version bump).
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from core.database import SessionLocal  # noqa: E402
from repositories.user_repository import UserRepository  # noqa: E402


def main(username: str, provider_id: str, subject: str) -> int:
    with SessionLocal() as db:
        users = UserRepository(db)
        user = users.get_by_username(username)
        if user is None:
            print(f"No such user: {username}", file=sys.stderr)
            return 1
        holder = users.get_by_oidc_identity(provider_id, subject)
        if holder is not None and holder.id != user.id:
            print(f"Identity already bound to user '{holder.username}'", file=sys.stderr)
            return 1
        users.update_user(
            user.id,
            oidc_provider=provider_id,
            oidc_subject=subject,
            token_version=user.token_version + 1,  # end existing sessions
        )
        print(f"Linked {username} to {provider_id}:{subject}")
        return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(*sys.argv[1:]))

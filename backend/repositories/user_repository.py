from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models.users import User
from repositories.updates import apply_updates

_UPDATABLE_FIELDS = frozenset(
    {
        "username",
        "password_hash",
        "is_active",
        "must_change_password",
        "token_version",
        "email",
        "display_name",
        "oidc_provider",
        "oidc_subject",
    }
)


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_by_username(self, username: str) -> User | None:
        return self.db.scalar(select(User).where(User.username == username))

    def count(self) -> int:
        return int(self.db.scalar(select(func.count()).select_from(User)) or 0)

    def get_by_username_ci(self, username: str) -> User | None:
        """Case-insensitive lookup: ``Admin`` and ``admin`` are the same account (S1-18)."""
        return self.db.scalar(
            select(User).where(func.lower(User.username) == username.strip().lower())
        )

    def get_by_oidc_identity(self, provider_id: str, subject: str) -> User | None:
        return self.db.scalar(
            select(User).where(
                User.oidc_provider == provider_id,
                User.oidc_subject == subject,
            )
        )

    def create_user(
        self,
        username: str,
        password_hash: str,
        is_active: bool = True,
        email: str | None = None,
        display_name: str | None = None,
        oidc_provider: str | None = None,
        oidc_subject: str | None = None,
        must_change_password: bool = False,
    ) -> User:
        user = User(
            username=username,
            password_hash=password_hash,
            is_active=is_active,
            email=email,
            display_name=display_name,
            oidc_provider=oidc_provider,
            oidc_subject=oidc_subject,
            must_change_password=must_change_password,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)

        return user

    def list_users(self, active_only: bool = False) -> list[User]:
        query = select(User).order_by(User.username)
        if active_only:
            query = query.where(User.is_active == True)  # noqa: E712
        return list(self.db.scalars(query))

    def update_user(
        self, user_id: int, *, bump_token_version: bool = False, **kwargs: object
    ) -> User | None:
        user = self.db.get(User, user_id)
        if user is None:
            return None
        apply_updates(
            user,
            {key: value for key, value in kwargs.items() if value is not None},
            _UPDATABLE_FIELDS,
        )
        if bump_token_version:
            # Increment in SQL (UPDATE ... SET token_version = token_version + 1) so two
            # concurrent bumps add two, instead of both writing "stale value + 1" (S1-13).
            user.token_version = User.token_version + 1
        self.db.commit()
        self.db.refresh(user)
        return user

    def delete_user(self, user_id: int) -> bool:
        user = self.db.get(User, user_id)
        if user is None:
            return False
        self.db.delete(user)
        self.db.commit()
        return True

    def set_active(self, user_id: int, is_active: bool) -> User | None:
        return self.update_user(user_id, is_active=is_active)

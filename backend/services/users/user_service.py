from __future__ import annotations

from sqlalchemy.orm import Session

from core.models.users import User
from repositories.user_repository import UserRepository
from services.auth.auth_service import password_hash


class UserService:
    def __init__(self, db: Session) -> None:
        self._repo = UserRepository(db)

    def list_users(self, active_only: bool = False) -> list[User]:
        return self._repo.list_users(active_only=active_only)

    def get_user(self, user_id: int) -> User | None:
        return self._repo.get_by_id(user_id)

    def create_user(self, username: str, password: str, is_active: bool = True) -> User:
        return self._repo.create_user(
            username=username,
            password_hash=password_hash.hash(password),
            is_active=is_active,
        )

    def update_user(
        self,
        user_id: int,
        username: str | None = None,
        password: str | None = None,
        is_active: bool | None = None,
    ) -> User | None:
        updates: dict[str, object] = {}
        if username is not None:
            updates["username"] = username
        if password is not None:
            updates["password_hash"] = password_hash.hash(password)
        if is_active is not None:
            updates["is_active"] = is_active
        return self._repo.update_user(user_id, **updates)

    def delete_user(self, user_id: int) -> bool:
        return self._repo.delete_user(user_id)

    def set_active(self, user_id: int, is_active: bool) -> User | None:
        return self._repo.set_active(user_id, is_active)

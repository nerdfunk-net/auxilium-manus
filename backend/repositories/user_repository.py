from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.users import User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_by_username(self, username: str) -> User | None:
        return self.db.scalar(select(User).where(User.username == username))

    def create_user(
        self,
        username: str,
        password_hash: str,
        is_active: bool = True,
    ) -> User:
        user = User(
            username=username,
            password_hash=password_hash,
            is_active=is_active,
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

    def update_user(self, user_id: int, **kwargs: object) -> User | None:
        user = self.db.get(User, user_id)
        if user is None:
            return None
        for key, value in kwargs.items():
            if value is not None and hasattr(user, key):
                setattr(user, key, value)
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

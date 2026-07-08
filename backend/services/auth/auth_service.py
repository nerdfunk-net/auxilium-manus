from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.config import DEFAULT_INITIAL_PASSWORD, settings
from core.models.users import User
from repositories.user_repository import UserRepository

password_hash = PasswordHash.recommended()
dummy_password_hash = password_hash.hash("dummy-password")
logger = logging.getLogger(__name__)


class AuthenticationError(RuntimeError):
    """Raised when credentials are invalid."""


class AuthService:
    def __init__(self, db: Session) -> None:
        self.users = UserRepository(db)

    def authenticate_user(self, username: str, password: str) -> User:
        user = self.users.get_by_username(username)
        stored_password_hash = user.password_hash if user is not None else dummy_password_hash
        is_valid_password = password_hash.verify(password, stored_password_hash)

        if user is None or not user.is_active or not is_valid_password:
            raise AuthenticationError("Invalid username or password")

        return user

    def create_access_token(self, user: User) -> tuple[str, int]:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
        expires_at = datetime.now(UTC) + expires_delta
        payload = {
            "sub": user.username,
            "user_id": user.id,
            "exp": expires_at,
        }

        token = jwt.encode(payload, settings.secret_key, algorithm="HS256")

        return token, int(expires_delta.total_seconds())

    def ensure_initial_admin(self) -> User:
        existing_user = self.users.get_by_username(settings.initial_username)

        if existing_user is not None:
            return existing_user

        if settings.initial_password == DEFAULT_INITIAL_PASSWORD:
            logger.warning(
                "Creating initial admin user with the default development password. "
                "Set INITIAL_PASSWORD in backend/.env before production use.",
            )

        try:
            return self.users.create_user(
                username=settings.initial_username,
                password_hash=password_hash.hash(settings.initial_password),
                is_active=True,
            )
        except IntegrityError:
            self.users.db.rollback()
            concurrent_user = self.users.get_by_username(settings.initial_username)

            if concurrent_user is None:
                raise

            return concurrent_user

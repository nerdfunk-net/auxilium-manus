from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.config import DEFAULT_INITIAL_PASSWORD, settings
from core.models.users import User
from repositories.user_repository import UserRepository
from services.auth.password_policy import validate_password

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

    def create_access_token(
        self,
        user: User,
        *,
        sid_iat: datetime | None = None,
    ) -> tuple[str, int]:
        """Mint an access token.

        ``sid_iat`` is the original login time, carried unchanged through every
        refresh. When omitted (fresh login), the session starts now.
        """
        now = datetime.now(UTC)
        session_started = sid_iat or now
        max_age = timedelta(hours=settings.session_max_age_hours)

        # Absolute cap: refuse to mint a token whose session is already too old.
        if now - session_started > max_age:
            raise AuthenticationError("Invalid authentication token")

        # Clamp exp so a token never outlives the absolute session deadline.
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
        session_deadline = session_started + max_age
        expires_at = min(now + expires_delta, session_deadline)

        payload = {
            "sub": user.username,
            "user_id": user.id,
            "iat": int(now.timestamp()),
            # Plain int timestamp so create / verify / refresh read back the same type.
            "sid_iat": int(session_started.timestamp()),
            "jti": secrets.token_urlsafe(16),
            "tv": user.token_version,
            "exp": expires_at,
        }

        token = jwt.encode(payload, settings.secret_key, algorithm="HS256")

        return token, int((expires_at - now).total_seconds())

    def refresh_access_token(self, token: str) -> tuple[User, str, int]:
        """Re-issue an access token from a signed JWT, allowing expired tokens.

        Still rejects tokens whose ``exp`` claim is older than
        ``settings.refresh_token_max_age_hours`` — otherwise a leaked access
        token could be exchanged for a fresh one indefinitely, making
        ACCESS_TOKEN_EXPIRE_MINUTES a no-op security boundary (see
        doc/FABLE-ANALYSIS.md §4.1).
        """
        try:
            payload = jwt.decode(
                token,
                settings.secret_key,
                algorithms=["HS256"],
                options={"verify_exp": False},
            )
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError("Invalid authentication token") from exc

        user_id = payload.get("user_id")
        username = payload.get("sub")
        expires_at_ts = payload.get("exp")
        if (
            not isinstance(user_id, int)
            or not isinstance(username, str)
            or not username
            or not isinstance(expires_at_ts, int | float)
        ):
            raise AuthenticationError("Invalid authentication token")

        expired_since = datetime.now(UTC) - datetime.fromtimestamp(expires_at_ts, UTC)
        if expired_since > timedelta(hours=settings.refresh_token_max_age_hours):
            raise AuthenticationError("Invalid authentication token")

        user = self.users.get_by_id(user_id)
        if user is None or not user.is_active or user.username != username:
            raise AuthenticationError("Invalid authentication token")

        # Strict: the token must carry a matching `tv` and a numeric `sid_iat`.
        # A pre-S5 token has neither and cannot be refreshed (intended).
        token_version = payload.get("tv")
        if not isinstance(token_version, int) or token_version != user.token_version:
            raise AuthenticationError("Invalid authentication token")

        sid_iat_raw = payload.get("sid_iat")
        if not isinstance(sid_iat_raw, int | float):
            raise AuthenticationError("Invalid authentication token")
        sid_iat = datetime.fromtimestamp(sid_iat_raw, UTC)

        # create_access_token re-checks the absolute session cap against sid_iat
        # and raises AuthenticationError if it is exceeded.
        access_token, expires_in = self.create_access_token(user, sid_iat=sid_iat)
        return user, access_token, expires_in

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
                must_change_password=True,  # bootstrap credential is never a long-term one
            )
        except IntegrityError:
            self.users.db.rollback()
            concurrent_user = self.users.get_by_username(settings.initial_username)

            if concurrent_user is None:
                raise

            return concurrent_user

    def bump_token_version(self, user_id: int) -> None:
        """Invalidate every outstanding access token for this user.

        Used by logout and (folded into the same write) by password / username
        change and deactivation.
        """
        user = self.users.get_by_id(user_id)
        if user is None:
            return
        # update_user skips None values; token_version is always >= 1 here.
        self.users.update_user(user_id, token_version=user.token_version + 1)

    def change_password(self, user: User, current_password: str, new_password: str) -> User:
        if not password_hash.verify(current_password, user.password_hash):
            raise AuthenticationError("Current password is incorrect")
        validate_password(new_password, username=user.username)  # PasswordPolicyError → 400
        updated = self.users.update_user(
            user.id,
            password_hash=password_hash.hash(new_password),
            must_change_password=False,
            token_version=user.token_version + 1,
        )
        return updated or user

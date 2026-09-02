from __future__ import annotations

from sqlalchemy.orm import Session

from core.domain_exceptions import AccessDeniedError
from core.models.users import User
from repositories.user_repository import UserRepository
from services.auth.auth_service import password_hash
from services.auth.password_policy import validate_password
from services.auth.rbac_service import RBACService


class UserService:
    def __init__(self, db: Session) -> None:
        self._repo = UserRepository(db)
        self._rbac = RBACService(db)

    def list_users(self, active_only: bool = False) -> list[User]:
        return self._repo.list_users(active_only=active_only)

    def get_user(self, user_id: int) -> User | None:
        return self._repo.get_by_id(user_id)

    def create_user(self, username: str, password: str, is_active: bool = True) -> User:
        validate_password(password, username=username)
        return self._repo.create_user(
            username=username,
            password_hash=password_hash.hash(password),
            is_active=is_active,
            must_change_password=True,  # admin-set password; user must replace it
        )

    def update_user(
        self,
        user_id: int,
        username: str | None = None,
        password: str | None = None,
        is_active: bool | None = None,
        *,
        actor_user_id: int | None = None,
    ) -> User | None:
        # Guards first, write once, so a request that renames and deactivates in
        # the same call either fully passes or fully fails (P1, P4, P6).
        self._rbac.may_touch_target(actor_user_id, user_id)
        if is_active is False:
            self._assert_can_remove(user_id, actor_user_id)

        target = self._repo.get_by_id(user_id)
        if password is not None:
            validate_password(password, username=username or (target.username if target else None))

        updates: dict[str, object] = {}
        if username is not None:
            updates["username"] = username
        if password is not None:
            updates["password_hash"] = password_hash.hash(password)
            updates["must_change_password"] = True  # admin-set password
        if is_active is not None:
            updates["is_active"] = is_active

        # Kill outstanding tokens when the credential or identity changes, or on
        # deactivation. Folded into the same write so the change is atomic.
        if (
            updates
            and target is not None
            and (
                "password_hash" in updates
                or "username" in updates
                or updates.get("is_active") is False
            )
        ):
            updates["token_version"] = target.token_version + 1

        return self._repo.update_user(user_id, **updates)

    def delete_user(self, user_id: int, *, actor_user_id: int | None = None) -> bool:
        self._assert_can_remove(user_id, actor_user_id)
        return self._repo.delete_user(user_id)

    def set_active(
        self, user_id: int, is_active: bool, *, actor_user_id: int | None = None
    ) -> User | None:
        if not is_active:
            self._assert_can_remove(user_id, actor_user_id)
            target = self._repo.get_by_id(user_id)
            if target is None:
                return None
            # Deactivation must also invalidate outstanding tokens.
            return self._repo.update_user(
                user_id, is_active=False, token_version=target.token_version + 1
            )
        return self._repo.set_active(user_id, is_active)

    def _assert_can_remove(self, user_id: int, actor_user_id: int | None) -> None:
        if actor_user_id is not None and actor_user_id == user_id:
            raise AccessDeniedError("You cannot delete or deactivate your own account")
        self._rbac.may_touch_target(actor_user_id, user_id)
        self._rbac.assert_not_last_admin(user_id)

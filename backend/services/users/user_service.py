from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from core.domain_exceptions import AccessDeniedError, ConflictError
from core.models.users import User
from core.password_policy import validate_password
from repositories.inventory_repository import InventoryRepository
from repositories.user_repository import UserRepository
from repositories.workflow_repository import WorkflowRepository
from services.auth.auth_service import password_hash
from services.auth.rbac_service import RBACService


class UserService:
    def __init__(self, db: Session, *, credentials_service: Any | None = None) -> None:
        self._db = db
        # Built with the OpenBao management client by the router, so a deleted user's
        # vault-backed credentials can be removed from the vault too (S3-07).
        self._credentials_service = credentials_service
        self._repo = UserRepository(db)
        self._rbac = RBACService(db)
        self._workflows = WorkflowRepository(db)
        self._inventories = InventoryRepository(db)  # same Session => one transaction (S14)

    def list_users(self, active_only: bool = False) -> list[User]:
        return self._repo.list_users(active_only=active_only)

    def get_user(self, user_id: int) -> User | None:
        return self._repo.get_by_id(user_id)

    def create_user(self, username: str, password: str, is_active: bool = True) -> User:
        validate_password(password, username=username)
        self._assert_username_free(username)
        return self._repo.create_user(
            username=username,
            password_hash=password_hash.hash(password),
            is_active=is_active,
            must_change_password=True,  # admin-set password; user must replace it
        )

    def _delete_private_credentials(self, user_id: int) -> None:
        from repositories.credentials_repository import CredentialsRepository

        service = self._credentials_service
        if service is None:
            from services.credentials.credentials_service import CredentialsService

            service = CredentialsService(self._db)
        for credential in CredentialsRepository(self._db).list_owned_by(user_id):
            if credential.visibility == "private":
                service.delete_credential(credential.id, acting_user_id=user_id)

    def _schedules(self):  # noqa: ANN202 - local import: schedule_service imports the user stack
        from services.execution.schedule_service import ScheduleService

        return ScheduleService(self._db)

    def _assert_username_free(self, username: str, *, except_user_id: int | None = None) -> None:
        """Usernames are unique case-insensitively (S1-18)."""
        existing = self._repo.get_by_username_ci(username)
        if existing is not None and existing.id != except_user_id:
            raise ConflictError("Username already exists")

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
        # the same call either fully passes or fully fails (P1, P4, P6, R1).
        self._rbac.may_touch_target(actor_user_id, user_id)
        if is_active is False:
            self._assert_can_remove(user_id, actor_user_id)
        if username is not None:
            self._assert_username_free(username, except_user_id=user_id)
        if password is not None or username is not None:
            # T2: bypassing the current-password check of /auth/change-password
            # through this admin endpoint is not allowed, for anyone.
            if actor_user_id is not None and actor_user_id == user_id:
                raise AccessDeniedError(
                    "You cannot change your own password or username here; "
                    "change your password via the change-password dialog "
                    "(an administrator renames accounts)"
                )
            # A password reset is an account takeover; a rename is an identity
            # change. Both are bounded by the target's effective rights (R1).
            self._rbac.assert_may_take_over(actor_user_id, user_id)

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
        bump = False
        if (
            updates
            and target is not None
            and (
                "password_hash" in updates
                or "username" in updates
                or updates.get("is_active") is False
            )
        ):
            bump = True

        if username is not None and target is not None and username != target.username:
            # S14: a private inventory must follow its owner to the new name, otherwise the old
            # name's next holder would inherit it. Executed here, committed by update_user below.
            self._inventories.reassign_creator(target.username, username)
        if updates.get("is_active") is False and target is not None:
            self._schedules().disable_for_user(user_id)
        return self._repo.update_user(user_id, bump_token_version=bump, **updates)

    def delete_user(self, user_id: int, *, actor_user_id: int | None = None) -> bool:
        self._assert_can_remove(user_id, actor_user_id)
        target = self._repo.get_by_id(user_id)
        if target is not None:
            # S14: nobody may inherit this user's private inventories by taking the name later.
            self._inventories.delete_private_created_by(target.username)
            # Their private credentials go with them (including the OpenBao secret): no orphan
            # may stay usable by a system context (S3-07). If the vault is down this raises and
            # the user is kept.
            self._delete_private_credentials(user_id)
            # Schedules fire as their creator: they go with the account (S2-04).
            self._schedules().delete_for_user(user_id)
            # Their workflows go to the acting administrator instead of becoming ownerless.
            if actor_user_id is not None:
                self._workflows.reassign_creator(user_id, actor_user_id)
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
            self._schedules().disable_for_user(user_id)
            return self._repo.update_user(user_id, is_active=False, bump_token_version=True)
        # R3 / P4: only an admin may bring a deactivated administrator back.
        # Approving a pending OIDC user (a non-admin target) still passes.
        self._rbac.may_touch_target(actor_user_id, user_id)
        return self._repo.set_active(user_id, is_active)

    def _assert_can_remove(self, user_id: int, actor_user_id: int | None) -> None:
        if actor_user_id is not None and actor_user_id == user_id:
            raise AccessDeniedError("You cannot delete or deactivate your own account")
        self._rbac.may_touch_target(actor_user_id, user_id)
        self._rbac.assert_not_last_admin(user_id)

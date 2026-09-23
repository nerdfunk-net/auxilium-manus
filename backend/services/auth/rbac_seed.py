from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass

from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from core.models.users import User
from repositories.rbac_repository import RBACRepository
from repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)

_password_hash = PasswordHash.recommended()

AI_ASSISTANT_USERNAME = "ai-assistant"

DEFAULT_PERMISSIONS: list[tuple[str, str, str]] = [
    ("git.repositories", "read", "View git repository configurations"),
    ("git.repositories", "write", "Create or update git repository configurations"),
    ("git.repositories", "delete", "Delete git repository configurations"),
    ("git.operations", "read", "View git repository status and info"),
    ("git.operations", "execute", "Sync (clone/pull/push) git repositories"),
    ("git.version_control", "read", "View git branches, commits, and diffs"),
    ("git.files", "read", "Browse files inside a git repository"),
    ("git.debug", "read", "View git repository diagnostics"),
    ("git.debug", "execute", "Run git debug probes (read/write/delete/push)"),
    ("sources.nautobot", "read", "View Nautobot-backed inventory sources"),
    ("sources.nautobot", "write", "Create or update Nautobot-backed inventory sources"),
    ("sources.nautobot", "delete", "Delete Nautobot-backed inventory sources"),
    ("sources.ise", "read", "View Cisco ISE sources and network devices"),
    ("sources.ise", "write", "Create or update Cisco ISE sources and network devices"),
    ("sources.ise", "delete", "Delete Cisco ISE sources and network devices"),
    ("sources.pyats", "read", "View pyATS shim sources"),
    ("sources.pyats", "write", "Create or update pyATS shim sources"),
    ("sources.pyats", "delete", "Delete pyATS shim sources"),
    ("sources.batfish", "read", "View Batfish sources and list networks/snapshots"),
    ("sources.batfish", "write", "Create or update Batfish sources"),
    ("sources.batfish", "delete", "Delete Batfish sources"),
    # Ad-hoc questions from the Template Editor return routing tables, ACL
    # verdicts, and extracted facts for ANY network on the coordinator --
    # including networks built by workflows the caller cannot see (B2).
    # Deliberately not a "read" action, so the seeded viewer role never gets it.
    ("sources.batfish", "query", "Run ad-hoc Batfish questions from the template editor"),
    ("sources.mattermost", "read", "View Mattermost sources"),
    ("sources.mattermost", "write", "Create or update Mattermost sources"),
    ("sources.mattermost", "delete", "Delete Mattermost sources"),
    ("secret_manager.connections", "read", "View secret manager connection configurations"),
    (
        "secret_manager.connections",
        "write",
        "Create or update secret manager connection configurations",
    ),
    ("secret_manager.connections", "delete", "Delete secret manager connection configurations"),
    ("nautobot.custom_fields", "read", "View Nautobot custom field definitions"),
    ("workflow_steps", "read", "View available workflow step plugins and configs"),
    ("workflows", "read", "View workflow definitions"),
    ("workflows", "write", "Create or update workflow definitions"),
    ("workflows", "delete", "Delete workflow definitions"),
    ("workflows", "execute", "Trigger, cancel, or step a workflow run"),
    ("workflows", "publish", "Publish or unpublish a workflow to the background execution tier"),
    ("workflow_runs", "read", "View workflow run history, logs, and artifacts"),
    ("workflow_runs", "delete", "Delete workflow run history"),
    ("change_requests", "read", "View change requests and rendered-config diffs"),
    ("change_requests", "approve", "Approve, deploy, or reject a change request"),
    ("netmiko", "execute", "Run commands against network devices via Netmiko"),
    ("credentials", "read", "View credential metadata"),
    ("credentials", "write", "Create or update credentials"),
    ("credentials", "delete", "Delete credentials"),
    ("credentials", "reveal", "View decrypted credential secrets"),
    ("templates", "read", "View and render command/config templates"),
    ("templates", "write", "Create or update templates"),
    ("templates", "delete", "Delete templates"),
    ("settings", "read", "View application settings"),
    ("settings", "write", "Create or update application settings"),
    ("hatchet_settings", "read", "View Hatchet workflow engine settings"),
    ("cache_settings", "read", "View cache/Redis settings and stats"),
    ("cache_settings", "write", "Update or clear cache/Redis settings"),
    ("logging_settings", "read", "View application logging configuration"),
    ("logging_settings", "write", "Update application logging configuration"),
    ("general_settings", "read", "View application general configuration"),
    ("general_settings", "write", "Update application general configuration"),
    ("rbac.permissions", "read", "View the permission catalog"),
    ("rbac.permissions", "write", "Create permissions"),
    ("rbac.permissions", "delete", "Delete permissions"),
    ("rbac.roles", "read", "View roles and their permissions"),
    ("rbac.roles", "write", "Create or update roles and role-permission assignments"),
    ("rbac.roles", "delete", "Delete roles"),
    ("users", "read", "View user accounts and their roles"),
    ("users", "write", "Create or update user accounts, roles, and permission overrides"),
    ("users", "delete", "Delete user accounts"),
    ("system.database", "read", "View database schema sync status"),
    ("system.database", "write", "Apply database schema migrations"),
    ("system.rbac", "write", "Re-seed or reset the RBAC permission/role catalog"),
    ("system.certificates", "read", "View CA certificate files and system trust status"),
    ("system.certificates", "write", "Upload, install, or remove CA certificate files"),
    ("system.oidc", "read", "View OIDC provider configuration and debug status"),
]

SYSTEM_ROLES: dict[str, str] = {
    "admin": "Full access to every resource and action",
    "viewer": "Read-only access to every resource",
    "ai-assistant": "Restricted role for the AI workflow-building assistant",
}

# Curated allowlist, not derived from DEFAULT_PERMISSIONS like admin ("everything")
# or viewer ("every read") — this role must never gain workflows:execute/publish/
# delete, change_requests:approve, credentials:reveal, or anything under
# rbac.*/users/system.*/secret_manager.* (see doc/ai_workflows/PROCESS.md).
AI_ASSISTANT_PERMISSIONS: list[tuple[str, str]] = [
    ("workflows", "read"),
    ("workflows", "write"),
    ("credentials", "read"),
    ("git.repositories", "read"),
    ("sources.nautobot", "read"),
    ("sources.mattermost", "read"),
    ("sources.batfish", "read"),
    ("sources.pyats", "read"),
]


def seed_rbac(db: Session) -> None:
    """Idempotently create the default permission catalog and system roles."""
    repo = RBACRepository(db)

    for resource, action, description in DEFAULT_PERMISSIONS:
        if repo.get_permission(resource, action) is None:
            repo.create_permission(resource, action, description)

    for role_name, role_description in SYSTEM_ROLES.items():
        if repo.get_role_by_name(role_name) is None:
            repo.create_role(role_name, description=role_description, is_system=True)

    admin_role = repo.get_role_by_name("admin")
    viewer_role = repo.get_role_by_name("viewer")

    for resource, action, _ in DEFAULT_PERMISSIONS:
        permission = repo.get_permission(resource, action)
        if permission is None:
            continue

        if admin_role is not None:
            repo.assign_permission_to_role(admin_role.id, permission.id, granted=True)

        if viewer_role is not None and action == "read":
            repo.assign_permission_to_role(viewer_role.id, permission.id, granted=True)

    ai_assistant_role = repo.get_role_by_name("ai-assistant")
    if ai_assistant_role is not None:
        for resource, action in AI_ASSISTANT_PERMISSIONS:
            permission = repo.get_permission(resource, action)
            if permission is not None:
                repo.assign_permission_to_role(ai_assistant_role.id, permission.id, granted=True)

    logger.info(
        "RBAC seed complete: %s permissions, %s system roles",
        len(DEFAULT_PERMISSIONS),
        len(SYSTEM_ROLES),
    )


def ensure_ai_assistant_user(db: Session) -> User:
    """Idempotently seed the restricted `ai-assistant` service account.

    Created inactive: this account never logs in interactively (its password is
    random and discarded), and `is_active=False` is the global kill-switch an admin
    must flip on in Settings -> Users before backend/scripts/ai_workflow_apply.py
    will do anything — see doc/ai_workflows/PROCESS.md. Callers pass their own
    UserRepository to keep this in the caller's transaction (mirrors
    AuthService.ensure_initial_admin's get-or-create idiom).
    """
    users = UserRepository(db)
    existing_user = users.get_by_username(AI_ASSISTANT_USERNAME)
    if existing_user is not None:
        return existing_user

    return users.create_user(
        username=AI_ASSISTANT_USERNAME,
        password_hash=_password_hash.hash(secrets.token_urlsafe(32)),
        is_active=False,
    )


def remove_all_rbac_data(db: Session) -> None:
    """Delete every role and permission. FK cascades clear role/user assignments."""
    repo = RBACRepository(db)

    for role in repo.list_roles():
        repo.delete_role(role.id)

    for permission in repo.list_permissions():
        repo.delete_permission(permission.id)

    logger.warning("RBAC data removed: all roles and permissions deleted")


@dataclass(frozen=True)
class RbacSeedResult:
    permissions_seeded: int
    roles_seeded: int
    removed_existing: bool


def admin_reseed_rbac(db: Session, *, remove_existing: bool = False) -> RbacSeedResult:
    """Re-seed the RBAC catalog, optionally wiping it first.

    A full wipe cascades-deletes user_roles, which would strip the calling
    admin's own role until the next app restart — so this re-runs the same
    admin-role-assignment step main.py's lifespan performs on every boot.
    """
    if remove_existing:
        remove_all_rbac_data(db)

    seed_rbac(db)

    from services.auth.auth_service import AuthService
    from services.auth.rbac_service import RBACService

    admin_user = AuthService(db).ensure_initial_admin()
    rbac = RBACService(db)
    # After a wipe nobody holds any role, so this still re-grants (intended —
    # remove_all_rbac_data cascaded user_roles). Without a wipe, respect a
    # deliberate demotion exactly as main.py's lifespan does (S10).
    if not rbac.role_has_members("admin"):
        rbac.assign_role_to_user_by_name(admin_user.id, "admin")

    repo = RBACRepository(db)
    return RbacSeedResult(
        permissions_seeded=len(repo.list_permissions()),
        roles_seeded=len(repo.list_roles()),
        removed_existing=remove_existing,
    )

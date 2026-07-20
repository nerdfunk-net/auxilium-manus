from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from repositories.rbac_repository import RBACRepository

logger = logging.getLogger(__name__)

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
    ("sources.git", "read", "Preview git-backed inventory sources"),
    ("sources.git", "execute", "Pull or re-clone git-backed inventory sources"),
    ("sources.nautobot", "read", "View Nautobot-backed inventory sources"),
    ("sources.nautobot", "write", "Create or update Nautobot-backed inventory sources"),
    ("sources.nautobot", "delete", "Delete Nautobot-backed inventory sources"),
    ("sources.ise", "read", "View Cisco ISE sources and network devices"),
    ("sources.ise", "write", "Create or update Cisco ISE sources and network devices"),
    ("sources.ise", "delete", "Delete Cisco ISE sources and network devices"),
    ("nautobot.custom_fields", "read", "View Nautobot custom field definitions"),
    ("workflow_steps", "read", "View available workflow step plugins and configs"),
    ("workflows", "read", "View workflow definitions"),
    ("workflows", "write", "Create or update workflow definitions"),
    ("workflows", "delete", "Delete workflow definitions"),
    ("workflows", "execute", "Trigger, cancel, or step a workflow run"),
    ("workflow_runs", "read", "View workflow run history, logs, and artifacts"),
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
    ("hatchet_settings", "write", "Update Hatchet workflow engine settings"),
    ("cache_settings", "read", "View cache/Redis settings and stats"),
    ("cache_settings", "write", "Update or clear cache/Redis settings"),
    ("logging_settings", "read", "View application logging configuration"),
    ("logging_settings", "write", "Update application logging configuration"),
    ("rbac.permissions", "read", "View the permission catalog"),
    ("rbac.permissions", "write", "Create permissions"),
    ("rbac.permissions", "delete", "Delete permissions"),
    ("rbac.roles", "read", "View roles and their permissions"),
    ("rbac.roles", "write", "Create or update roles and role-permission assignments"),
    ("rbac.roles", "delete", "Delete roles"),
    ("users", "read", "View user accounts and their roles"),
    ("users", "write", "Create or update user accounts, roles, and permission overrides"),
    ("users", "delete", "Delete user accounts"),
]

SYSTEM_ROLES: dict[str, str] = {
    "admin": "Full access to every resource and action",
    "viewer": "Read-only access to every resource",
}


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

    logger.info(
        "RBAC seed complete: %s permissions, %s system roles",
        len(DEFAULT_PERMISSIONS),
        len(SYSTEM_ROLES),
    )

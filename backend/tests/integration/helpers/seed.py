"""Seed helpers — build the DB rows the API would create, idempotently.

Every helper is safe to call again on a test DB that was not dropped: it
removes any stale row with the same name/key first, then recreates it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from core.domain_exceptions import ConflictError, NotFoundError
from models.settings import SettingCreate
from services.credentials.credentials_service import CredentialsService
from services.credentials.exceptions import CredentialNameConflictError, CredentialNotFoundError
from services.git.repository_service import GitRepositoryService
from services.settings.settings_service import SettingsService


def seed_nautobot_source(
    db: Session,
    *,
    source_id: str,
    url: str,
    token: str,
    verify_ssl: bool = False,
) -> str:
    """Create ``sources.nautobot.<id>`` exactly the way the API does.

    ``SettingsService.create_setting`` moves ``token`` into a global
    ``Credential`` and stores its ``credential_id`` on the setting value — the
    shape ``resolve_nautobot_credentials`` reads back. Returns the source id.
    """
    key = f"sources.nautobot.{source_id}"
    service = SettingsService(db)
    try:
        service.delete_setting(key)
    except NotFoundError:
        pass

    try:
        service.create_setting(
            SettingCreate(
                key=key,
                value={"url": url, "verify_ssl": verify_ssl, "token": token},
                description="integration-test nautobot source",
            )
        )
    except ConflictError:
        pass
    return source_id


def _delete_credential_by_name(db: Session, name: str) -> None:
    service = CredentialsService(db)
    for cred in service.list_credentials(
        include_expired=True, source="general", acting_user_id=None
    ):
        if cred["name"] == name:
            try:
                service.delete_credential(int(cred["id"]))
            except CredentialNotFoundError:
                pass


def seed_ssh_credential(
    db: Session,
    *,
    name: str = "itest-ssh",
    username: str,
    password: str,
) -> str:
    """Create a global ``ssh`` credential usable by ``resolve_ssh_credential``.

    Returns the credential name (the value steps reference).
    """
    _delete_credential_by_name(db, name)
    try:
        CredentialsService(db).create_credential(
            name=name,
            username=username,
            cred_type="ssh",
            password=password,
            source="general",
            visibility="global",
        )
    except CredentialNameConflictError:
        pass
    return name


def seed_git_repository(
    db: Session,
    *,
    name: str = "itest",
    url: str,
    branch: str = "main",
    token: str,
    credential_name: str = "itest-git",
    category: str = "device_configs",
    verify_ssl: bool = False,
) -> dict[str, Any]:
    """Create a global ``token`` credential + a ``git_repositories`` row.

    Returns ``{"id": int, "repository": <_to_dict()>, "credential_name": str}``.
    """
    _delete_credential_by_name(db, credential_name)
    try:
        CredentialsService(db).create_credential(
            name=credential_name,
            username="git",
            cred_type="token",
            password=token,
            source="general",
            visibility="global",
        )
    except CredentialNameConflictError:
        pass

    service = GitRepositoryService(db)
    existing = next(
        (r for r in service.get_repositories(active_only=False) if r["name"] == name),
        None,
    )
    if existing is not None:
        service.delete_repository(int(existing["id"]), hard_delete=True)

    repo_id = service.create_repository(
        {
            "name": name,
            "category": category,
            "url": url,
            "branch": branch,
            "auth_type": "token",
            "credential_name": credential_name,
            "verify_ssl": verify_ssl,
            "is_active": True,
        }
    )
    return {
        "id": repo_id,
        "repository": service.get_repository(repo_id),
        "credential_name": credential_name,
    }

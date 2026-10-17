"""What still uses a credential (O1-04).

Deleting a credential used to leave dangling references that only failed at the next run.
``find_dependants`` lists them as kind, id and name; it never returns a secret.

Git repositories, secret-manager connections and the mail settings resolve *global* credentials
only, so a private credential cannot be one of their dependants. A workflow canvas references a
credential by name and resolves a private one of the same name first, so a private credential is
only a dependant of its owner's workflows. Name matches are conservative: a global and a private
credential sharing a name are both reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from core.models.credentials import Credential
from core.source_keys import parse_source_key
from services.mail.mail_settings_service import SETTINGS_KEY as MAIL_SETTINGS_KEY


@dataclass(frozen=True)
class CredentialDependant:
    kind: str
    id: int
    name: str


class _UsageRepository(Protocol):
    def git_repositories_using(self, credential_name: str) -> list[tuple[int, str]]: ...
    def secret_managers_using(self, credential_name: str) -> list[tuple[int, str]]: ...
    def templates_using(self, credential_id: int) -> list[tuple[int, str]]: ...
    def settings_values(self) -> list[tuple[int, str, dict[str, Any]]]: ...
    def workflow_canvases(self) -> list[tuple[int, str, int | None, list[Any]]]: ...


def find_dependants(repo: _UsageRepository, credential: Credential) -> list[CredentialDependant]:
    is_private = credential.visibility == "private"
    found: list[CredentialDependant] = []

    if not is_private:
        found.extend(
            CredentialDependant("git_repository", item_id, name)
            for item_id, name in repo.git_repositories_using(credential.name)
        )
        found.extend(
            CredentialDependant("secret_manager", item_id, name)
            for item_id, name in repo.secret_managers_using(credential.name)
        )
    found.extend(
        CredentialDependant("template", item_id, name)
        for item_id, name in repo.templates_using(credential.id)
    )
    found.extend(_settings_dependants(repo, credential, is_private=is_private))
    found.extend(_workflow_dependants(repo, credential, is_private=is_private))
    return found


def _settings_dependants(
    repo: _UsageRepository, credential: Credential, *, is_private: bool
) -> list[CredentialDependant]:
    found: list[CredentialDependant] = []
    for row_id, key, value in repo.settings_values():
        source_id = value.get("credential_id")
        if (
            parse_source_key(key) is not None
            and isinstance(source_id, int)
            and not isinstance(source_id, bool)
            and source_id == credential.id
        ):
            found.append(CredentialDependant("source", row_id, key))
        elif (
            key == MAIL_SETTINGS_KEY
            and not is_private
            and value.get("credential_name") == credential.name
        ):
            found.append(CredentialDependant("mail_settings", row_id, key))
    return found


def _workflow_dependants(
    repo: _UsageRepository, credential: Credential, *, is_private: bool
) -> list[CredentialDependant]:
    return [
        CredentialDependant("workflow", workflow_id, name)
        for workflow_id, name, creator_id, nodes in repo.workflow_canvases()
        if (not is_private or creator_id == credential.owner_user_id)
        and any(_node_references(node, credential.name) for node in nodes)
    ]


def _node_references(node: Any, credential_name: str) -> bool:
    data = node.get("data") if isinstance(node, dict) else None
    config = data.get("pluginConfig") if isinstance(data, dict) else None
    return isinstance(config, dict) and config.get("credential_reference") == credential_name

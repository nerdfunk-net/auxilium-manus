#!/usr/bin/env python3
"""Structured, live-checkable counterpart to doc/ai_workflows/AI_DEFAULTS.md.

AI_DEFAULTS.md carries the "why" for each default; this module (backed by
scripts/ai_defaults.yaml) is the source of truth for the actual VALUES and is
the one place that resolves them against the live database — see
doc/ai_workflows/PROCESS.md's "AI_DEFAULTS.md resolver/drift-check" item.
Nothing here is re-derived by hand each session anymore: resolve_and_check()
either returns every default's current id, or raises AiDefaultsDriftError
naming exactly which entry no longer resolves (a renamed/deleted credential,
git repository, source, or inventory) — AI_DEFAULTS.md's own stated rule
("resolve live or fail loudly") is now enforced in code, not by convention.

Deliberately separate from ai_workflow_apply.py's job: that script still
never CHOOSES which defaults to use (see its docstring) — it only gates what
a caller already put in a patch (see REFERENCE_DRIFT_CODES below, which it
imports to fail loudly on a drifted reference instead of writing anyway).
This module is for whoever is about to draft a patch — the AI collaborator,
or a human — to get current ids and to catch a stale AI_DEFAULTS.md entry
*before* it ever reaches a patch file.

Usage (from backend/, with the project venv)::

    python scripts/ai_defaults.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from repositories.inventory_repository import InventoryRepository  # noqa: E402
from repositories.settings_repository import SettingsRepository  # noqa: E402
from services.credentials.credentials_service import CredentialsService  # noqa: E402
from services.git.repository_service import GitRepositoryService  # noqa: E402

_DEFAULTS_FILE = Path(__file__).resolve().parent / "ai_defaults.yaml"

# Tier 2 validation finding codes (services/workflow/workflow_validation_service.py)
# that mean "a name a patch referenced no longer resolves". Shared with
# ai_workflow_apply.py so both agree on exactly what counts as reference drift.
REFERENCE_DRIFT_CODES = frozenset(
    {
        "credential_reference_not_found",
        "credential_reference_wrong_type",
        "credential_reference_expired",
        "git_repository_not_found",
        "source_not_found",
    }
)

# config field -> source type, matching WorkflowValidationService's
# _SOURCE_ID_FIELDS. Sources are name-keyed at runtime (Settings row
# "sources.<type>.<name>"), so there is no numeric id to resolve here — only
# existence to confirm.
_SOURCE_FIELD_TYPE = {
    "nautobot_source_id": "nautobot",
    "mattermost_source_id": "mattermost",
    "batfish_source_id": "batfish",
    "pyats_source_id": "pyats",
    "ise_source_id": "ise",
}


class AiDefaultsDriftError(RuntimeError):
    """A name in ai_defaults.yaml no longer resolves against the live
    database — a signal the doc is stale, never something to paper over with
    a guess or a cached id."""


@dataclass(frozen=True)
class ResolvedAiDefaults:
    policy: dict[str, Any]
    credentials: dict[str, dict[str, Any]]  # key -> {name, type, id}
    git_repository_ids: dict[str, int]  # category -> live git_repository id
    sources: dict[str, str]  # config field -> name (existence already checked)
    inventory_ids: dict[str, int]  # purpose -> live inventory id


def load_ai_defaults_yaml() -> dict[str, Any]:
    with _DEFAULTS_FILE.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def resolve_and_check(
    db: Any,
    *,
    acting_username: str,
    acting_user_id: int | None = None,
) -> ResolvedAiDefaults:
    """Live-resolve every entry in ai_defaults.yaml, raising
    AiDefaultsDriftError on the first one that no longer exists."""
    raw = load_ai_defaults_yaml()

    credentials_raw: dict[str, dict[str, Any]] = raw.get("credentials", {})
    live_credentials = CredentialsService(db).list_credentials(
        include_expired=True, source="general", acting_user_id=acting_user_id
    )
    by_name = {c["name"]: c for c in live_credentials}
    resolved_credentials: dict[str, dict[str, Any]] = {}
    for key, entry in credentials_raw.items():
        name, expected_type = entry["name"], entry["type"]
        match = by_name.get(name)
        if match is None:
            raise AiDefaultsDriftError(
                f"ai_defaults.yaml credentials.{key}: no credential named {name!r} "
                f"exists anymore — has it been renamed or deleted?"
            )
        if match["type"] != expected_type:
            raise AiDefaultsDriftError(
                f"ai_defaults.yaml credentials.{key}: {name!r} is now type "
                f"{match['type']!r}, expected {expected_type!r}."
            )
        resolved_credentials[key] = {"name": name, "type": expected_type, "id": match["id"]}

    git_repos_raw: dict[str, str] = raw.get("git_repositories", {})
    repo_service = GitRepositoryService(db)
    resolved_git_repos: dict[str, int] = {}
    for category, name in git_repos_raw.items():
        matches = [
            r
            for r in repo_service.get_repositories(category=category, active_only=True)
            if r["name"] == name
        ]
        if not matches:
            raise AiDefaultsDriftError(
                f"ai_defaults.yaml git_repositories.{category}: no active repository "
                f"named {name!r} in category {category!r} — has it been renamed, "
                f"deleted, or deactivated?"
            )
        resolved_git_repos[category] = matches[0]["id"]

    sources_raw: dict[str, str] = raw.get("sources", {})
    settings_repo = SettingsRepository(db)
    resolved_sources: dict[str, str] = {}
    for field_name, name in sources_raw.items():
        source_type = _SOURCE_FIELD_TYPE.get(field_name, field_name.removesuffix("_source_id"))
        if settings_repo.get_by_key(f"sources.{source_type}.{name}") is None:
            raise AiDefaultsDriftError(
                f"ai_defaults.yaml sources.{field_name}: source {name!r} of type "
                f"{source_type!r} is not configured under Settings -> Sources."
            )
        resolved_sources[field_name] = name

    inventories_raw: dict[str, str] = raw.get("inventories", {})
    inventory_repo = InventoryRepository(db)
    resolved_inventories: dict[str, int] = {}
    for purpose, name in inventories_raw.items():
        inventory = inventory_repo.get_by_name(name, username=acting_username)
        if inventory is None:
            raise AiDefaultsDriftError(
                f"ai_defaults.yaml inventories.{purpose}: no active inventory named "
                f"{name!r} — has it been renamed, deleted, or deactivated?"
            )
        resolved_inventories[purpose] = inventory.id

    return ResolvedAiDefaults(
        policy=raw.get("policy", {}),
        credentials=resolved_credentials,
        git_repository_ids=resolved_git_repos,
        sources=resolved_sources,
        inventory_ids=resolved_inventories,
    )


def main() -> int:
    from core.database import SessionLocal
    from services.auth.rbac_seed import AI_ASSISTANT_USERNAME

    with SessionLocal() as db:
        try:
            resolved = resolve_and_check(db, acting_username=AI_ASSISTANT_USERNAME)
        except AiDefaultsDriftError as exc:
            print(json.dumps({"error": str(exc)}))
            return 1

        print(
            json.dumps(
                {
                    "policy": resolved.policy,
                    "credentials": resolved.credentials,
                    "git_repository_ids": resolved.git_repository_ids,
                    "sources": resolved.sources,
                    "inventory_ids": resolved.inventory_ids,
                },
                indent=2,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

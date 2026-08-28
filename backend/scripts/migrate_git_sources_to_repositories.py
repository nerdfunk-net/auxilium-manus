#!/usr/bin/env python3
"""One-off migration: fold ``sources.git.*`` Settings rows into ``GitRepository`` rows.

Background: the codebase used to have two parallel git config systems — the
Settings-KV-backed ``sources.git.*`` rows (used by workflow steps like git-clone,
git-pull, get-git-devices, store-artifact, ...) and the DB-backed ``GitRepository``
table (full CRUD, SSH-key + token auth, version control). Both have been consolidated
onto ``GitRepository``; this script migrates the data for anyone with existing
``sources.git.*`` entries.

For each ``sources.git.<source_id>`` Setting row, creates a ``GitRepository`` row
(category="workflow_steps") reusing the existing auto-created ``Credential`` named
``git-<source_id>`` (token auth). It then rewrites every workflow's ``canvas_nodes``
so any git-consuming step's ``git_source_id`` (string) config field becomes
``git_repository_id`` (int), pointing at the newly created repository.

Usage (run from backend/ with the project venv active):
  python scripts/migrate_git_sources_to_repositories.py                # dry run (report only)
  python scripts/migrate_git_sources_to_repositories.py --apply        # write changes
  python scripts/migrate_git_sources_to_repositories.py --apply --delete-old
      # also remove the migrated sources.git.* Setting rows (run only after
      # verifying the --apply output looks correct)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from core.database import SessionLocal  # noqa: E402
from core.models.workflows import Workflow  # noqa: E402
from repositories.git.git_repository_repository import GitRepositoryRepository  # noqa: E402
from repositories.settings_repository import SettingsRepository  # noqa: E402
from services.credentials.credentials_service import CredentialsService  # noqa: E402
from services.git.repository_service import GitRepositoryService  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate_git_sources")

_GIT_KEY_PREFIX = "sources.git."
_GIT_STEP_KINDS = frozenset(
    {
        "git-clone",
        "git-pull",
        "git-push",
        "get-git-devices",
        "store-artifact",
        "get-from-config",
        "read-config",
        "compare-data",
        "compare-pyats-snapshot",
    }
)
# set-default-attributes nests its git config under pluginConfig["git"]["git_source_id"]
_NESTED_GIT_CONFIG_STEP_KINDS = frozenset({"set-default-attributes"})


def _unique_name(desired: str, existing_names: set[str]) -> str:
    if desired not in existing_names:
        return desired
    suffix = 2
    while f"{desired}-{suffix}" in existing_names:
        suffix += 1
    return f"{desired}-{suffix}"


def _rewrite_config(config: dict[str, Any], repository_id: int) -> dict[str, Any]:
    new_config = {k: v for k, v in config.items() if k != "git_source_id"}
    new_config["git_repository_id"] = repository_id
    return new_config


def _rewrite_node(
    node: dict[str, Any],
    *,
    id_by_source_id: dict[str, int],
    orphaned: list[str],
    workflow_uuid: str,
) -> tuple[dict[str, Any], bool]:
    data = node.get("data") or {}
    kind = data.get("kind", "")
    config = data.get("pluginConfig")
    if not isinstance(config, dict):
        return node, False

    if kind in _GIT_STEP_KINDS and "git_source_id" in config:
        source_id = str(config.get("git_source_id") or "").strip().lower()
        repository_id = id_by_source_id.get(source_id)
        if repository_id is None:
            if source_id:
                orphaned.append(
                    f"workflow {workflow_uuid} node {node.get('id')}: "
                    f"git_source_id={source_id!r} has no migrated repository"
                )
            return node, False
        new_config = _rewrite_config(config, repository_id)
        new_node = {**node, "data": {**data, "pluginConfig": new_config}}
        return new_node, True

    if kind in _NESTED_GIT_CONFIG_STEP_KINDS:
        git_block = config.get("git")
        if isinstance(git_block, dict) and "git_source_id" in git_block:
            source_id = str(git_block.get("git_source_id") or "").strip().lower()
            repository_id = id_by_source_id.get(source_id)
            if repository_id is None:
                if source_id:
                    orphaned.append(
                        f"workflow {workflow_uuid} node {node.get('id')}: "
                        f"git_source_id={source_id!r} has no migrated repository"
                    )
                return node, False
            new_git_block = _rewrite_config(git_block, repository_id)
            new_config = {**config, "git": new_git_block}
            new_node = {**node, "data": {**data, "pluginConfig": new_config}}
            return new_node, True

    return node, False


def migrate(*, apply: bool, delete_old: bool) -> None:
    if delete_old and not apply:
        logger.error("--delete-old requires --apply")
        sys.exit(1)

    db = SessionLocal()
    try:
        settings_repo = SettingsRepository(db)
        git_settings = settings_repo.list_all(key_prefix=_GIT_KEY_PREFIX)
        if not git_settings:
            logger.info("No %s* settings found — nothing to migrate.", _GIT_KEY_PREFIX)

        repo_service = GitRepositoryService(db)
        git_repo_repo = GitRepositoryRepository(db)
        credentials = CredentialsService(db)
        existing_credential_names = {
            c["name"] for c in credentials.list_credentials(include_expired=True, source=None)
        }
        existing_names = {r.name for r in git_repo_repo.get_all(db=db)}

        id_by_source_id: dict[str, int] = {}
        for setting in git_settings:
            source_id = setting.key[len(_GIT_KEY_PREFIX) :]
            value = setting.value or {}
            name = _unique_name(source_id, existing_names)
            credential_name = f"git-{source_id}"

            if credential_name not in existing_credential_names:
                logger.warning(
                    "%s: expected credential '%s' not found — repository will be created "
                    "without a working credential",
                    setting.key,
                    credential_name,
                )

            logger.info(
                "%s GitRepository(name=%r, category=workflow_steps, url=%r, "
                "credential_name=%r) from %s",
                "Creating" if apply else "Would create",
                name,
                value.get("url"),
                credential_name,
                setting.key,
            )

            if apply:
                repo_id = repo_service.create_repository(
                    {
                        "name": name,
                        "category": "workflow_steps",
                        "url": value.get("url") or "",
                        "branch": value.get("branch") or "main",
                        "auth_type": "token",
                        "credential_name": credential_name,
                        "verify_ssl": value.get("verify_ssl", True),
                        "description": f"Migrated from {setting.key}",
                    }
                )
                id_by_source_id[source_id] = repo_id

            existing_names.add(name)

        if apply:
            db.commit()

        workflows = db.execute(select(Workflow)).scalars().all()
        orphaned: list[str] = []
        rewritten = 0
        for workflow in workflows:
            nodes = workflow.canvas_nodes or []
            new_nodes: list[dict[str, Any]] = []
            any_changed = False
            for node in nodes:
                new_node, changed = _rewrite_node(
                    node,
                    id_by_source_id=id_by_source_id,
                    orphaned=orphaned,
                    workflow_uuid=workflow.uuid,
                )
                new_nodes.append(new_node)
                any_changed = any_changed or changed

            if any_changed:
                rewritten += 1
                logger.info(
                    "%s workflow %s (%r)",
                    "Updating" if apply else "Would update",
                    workflow.uuid,
                    workflow.name,
                )
                if apply:
                    workflow.canvas_nodes = new_nodes

        if apply:
            db.commit()

        logger.info("%s %d workflow(s).", "Rewrote" if apply else "Would rewrite", rewritten)
        if orphaned:
            logger.warning(
                "%d orphaned git_source_id reference(s) — no migrated repository was found "
                "for these; reconfigure the affected steps by hand:",
                len(orphaned),
            )
            for line in orphaned:
                logger.warning("  %s", line)

        if delete_old:
            for setting in git_settings:
                settings_repo.delete(setting)
            db.commit()
            logger.info("Deleted %d %s* setting row(s).", len(git_settings), _GIT_KEY_PREFIX)
        elif apply:
            logger.info(
                "Old %s* setting rows left in place — rerun with --delete-old once verified.",
                _GIT_KEY_PREFIX,
            )
    finally:
        db.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate sources.git.* Settings rows into GitRepository rows."
    )
    parser.add_argument(
        "--apply", action="store_true", help="Write changes (default: dry-run report only)."
    )
    parser.add_argument(
        "--delete-old",
        action="store_true",
        help="Also delete the migrated sources.git.* Setting rows. Requires --apply.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    migrate(apply=args.apply, delete_old=args.delete_old)

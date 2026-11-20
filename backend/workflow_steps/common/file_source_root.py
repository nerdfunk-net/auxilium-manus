"""Resolve the root directory a file-reading step reads from.

One implementation for ``read-from-file``, ``read-config`` and ``enrich-attributes``: the
default export directory (``filesystem``) or a checked-out Git repository (``git``). In git
mode the repository lease is held until the caller's ``AsyncExitStack`` closes (C2-06). By default a
repository that cannot be refreshed fails the step unless ``allow_stale`` is set (the stale read
is then recorded as a warning by ``services.git.sync.git_checkout``). With ``refresh=False`` the
repository is not pulled at all and the local copy is read as it is (the read is recorded as a run
event with the commit); that is a choice of the step, not the strict-pull guarantee.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path

from core.database import get_db_session
from services.general.general_settings_service import GeneralSettingsService
from services.git.sync import agit_checkout
from workflow_steps.common.git_repository_loader import load_git_repository


def resolve_filesystem_root() -> Path:
    """The default export directory (Settings → General)."""
    db = get_db_session()
    try:
        return GeneralSettingsService(db).resolved_export_directory()
    finally:
        db.close()


async def resolve_git_root(
    git_repository_id: int,
    stack: AsyncExitStack,
    *,
    allow_stale: bool = False,
    refresh: bool = True,
) -> Path:
    """Check the repository out; the lease is held until *stack* closes. ``refresh=False`` reads
    the local copy without pulling (the lease is still taken)."""
    loop = asyncio.get_running_loop()
    repository = await loop.run_in_executor(None, lambda: load_git_repository(git_repository_id))
    return await stack.enter_async_context(
        agit_checkout(repository, allow_stale=allow_stale, refresh=refresh)
    )


async def resolve_source_root(
    *,
    source: str,
    git_repository_id: int | None,
    stack: AsyncExitStack,
    allow_stale: bool = False,
    refresh: bool = True,
    step_id: str,
) -> Path:
    """Root for source ``git`` or ``filesystem`` (git without a repository id: ``ValueError``)."""
    if source == "git":
        if git_repository_id is None:
            raise ValueError(f"{step_id}: git_repository_id is required when source=git")
        return await resolve_git_root(
            git_repository_id, stack, allow_stale=allow_stale, refresh=refresh
        )
    return await asyncio.get_running_loop().run_in_executor(None, resolve_filesystem_root)

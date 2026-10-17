"""Files written by the log-attributes step, and their retention (C6-03).

Layout: ``<data dir>/log-attributes/<workflow id>/<run uuid>/<filename>``. They live outside the
artifact store, so they are removed with their run (``RunService.delete_run``) and by the retention
sweep once the run no longer exists.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from core.config import settings

logger = logging.getLogger(__name__)

LOG_ATTRIBUTES_DIRNAME = "log-attributes"
# A directory younger than this is kept: its run may have been created after the sweep took its
# snapshot of run uuids (same rule as the artifact sweep).
ORPHAN_GRACE_SECONDS = 3600


def log_attributes_root() -> Path:
    return settings.data_directory / LOG_ATTRIBUTES_DIRNAME


def delete_run_dir(workflow_id: int | str, run_uuid: str, *, root: Path | None = None) -> bool:
    """Remove one run's log-attribute files; ``True`` when a directory was removed."""
    base = root or log_attributes_root()
    target = base / str(workflow_id) / run_uuid
    if not target.is_dir():
        return False
    shutil.rmtree(target, ignore_errors=True)
    return True


def purge_orphaned_dirs(
    valid_run_uuids: set[str], *, root: Path | None = None, now: float | None = None
) -> int:
    """Remove run directories whose run no longer exists (and are past the grace period)."""
    base = root or log_attributes_root()
    if not base.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - ORPHAN_GRACE_SECONDS
    removed = 0
    for workflow_dir in base.iterdir():
        if not workflow_dir.is_dir():
            continue
        for run_dir in workflow_dir.iterdir():
            if not run_dir.is_dir() or run_dir.name in valid_run_uuids:
                continue
            try:
                if run_dir.stat().st_mtime > cutoff:
                    continue
            except FileNotFoundError:
                logger.debug("Log-attribute directory vanished during purge: %s", run_dir)
                continue
            shutil.rmtree(run_dir, ignore_errors=True)
            removed += 1
        if not any(workflow_dir.iterdir()):
            workflow_dir.rmdir()
    logger.info("Purged %s orphaned log-attribute run directorie(s)", removed)
    return removed

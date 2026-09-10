"""Resolve the git ref a deploy run should operate on.

When a WorkflowRun was dispatched by a ChangeRequest approval
(``run.change_request_id`` is set), a ``git-pull`` / ``git-clone`` step with
``use_change_request_branch=true`` targets the change request's per-change
branch (``manus/cr-{id}``) instead of the repository's default branch. See
``doc/CICD_PIPELINE.md``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def resolve_cr_ref(run: Any) -> tuple[str, str] | None:
    """Return ``(branch, commit_sha)`` for the change request this run deploys,
    or ``None`` when the run is not a deploy run or the change request has no
    branch recorded.
    """
    change_request_id = getattr(run, "change_request_id", None)
    if not change_request_id:
        return None

    from core.database import get_db_session
    from repositories.change_request_repository import ChangeRequestRepository

    db = get_db_session()
    try:
        change_request = ChangeRequestRepository(db).get_by_id(int(change_request_id))
    finally:
        db.close()

    if change_request is None or not change_request.branch:
        return None
    return change_request.branch, change_request.commit_sha or ""

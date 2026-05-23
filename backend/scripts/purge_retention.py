#!/usr/bin/env python3
"""Purge old workflow runs and step logs from PostgreSQL.

Deletes workflow_runs in terminal states (success, failed, cancelled) older than
RUN_RETENTION_DAYS. workflow_step_results rows cascade automatically.

Schedule via cron, e.g. daily at 03:00:
  0 3 * * * cd /path/to/auxilium-manus/backend && ../.venv/bin/python scripts/purge_retention.py

Usage:
  python scripts/purge_retention.py              # respects RUN_RETENTION_ENABLED
  python scripts/purge_retention.py --dry-run    # count only
  python scripts/purge_retention.py --force      # run even when disabled in .env
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from core.config import settings  # noqa: E402
from core.database import SessionLocal  # noqa: E402
from services.execution.retention_service import RetentionService  # noqa: E402

logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Purge old workflow runs and step logs.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many runs would be deleted without deleting.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even when RUN_RETENTION_ENABLED is false.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Override RUN_RETENTION_DAYS from the environment.",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format=settings.log_format,
    )

    args = _parse_args()

    if not settings.run_retention_enabled and not args.force and not args.dry_run:
        logger.warning(
            "Retention is disabled (RUN_RETENTION_ENABLED=false). "
            "Use --dry-run to preview or --force to purge anyway."
        )
        return 0

    retention_days = args.days if args.days is not None else settings.run_retention_days
    if retention_days < 1:
        logger.error("Retention days must be at least 1")
        return 1

    with SessionLocal() as db:
        result = RetentionService(db).purge_workflow_runs(
            retention_days=retention_days,
            batch_size=settings.run_retention_batch_size,
            dry_run=args.dry_run,
        )

    action = "Would delete" if result.dry_run else "Deleted"
    print(  # noqa: T201
        f"{action} {result.runs_deleted} run(s) "
        f"older than {result.retention_days} day(s) (before {result.cutoff.isoformat()})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

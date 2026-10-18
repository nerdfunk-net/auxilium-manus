from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, defer

from core.models.report_snapshots import ReportSnapshot


class ReportSnapshotsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, snapshot_id: int) -> ReportSnapshot | None:
        return self.db.get(ReportSnapshot, snapshot_id)

    def create(self, **kwargs) -> ReportSnapshot:
        snapshot = ReportSnapshot(**kwargs)
        self.db.add(snapshot)
        self.db.commit()
        self.db.refresh(snapshot)
        return snapshot

    def list_snapshots(
        self, *, definition_id: int | None = None, limit: int = 200
    ) -> list[ReportSnapshot]:
        """Snapshots newest first; ``content`` can be megabytes, so it is not loaded."""
        stmt = (
            select(ReportSnapshot)
            .options(defer(ReportSnapshot.content))
            .order_by(ReportSnapshot.generated_at.desc(), ReportSnapshot.id.desc())
            .limit(limit)
        )
        if definition_id is not None:
            stmt = stmt.where(ReportSnapshot.definition_id == definition_id)
        return list(self.db.scalars(stmt))

    def stats_by_definition(self) -> dict[int, tuple[int, datetime | None]]:
        """``{definition_id: (count, last_generated_at)}`` for definitions that have snapshots."""
        stmt = (
            select(
                ReportSnapshot.definition_id,
                func.count(ReportSnapshot.id),
                func.max(ReportSnapshot.generated_at),
            )
            .where(ReportSnapshot.definition_id.is_not(None))
            .group_by(ReportSnapshot.definition_id)
        )
        return {
            definition_id: (count, last_generated_at)
            for definition_id, count, last_generated_at in self.db.execute(stmt)
            if definition_id is not None
        }

    def detach_definition(self, definition_id: int) -> None:
        """Clear ``definition_id`` (portable ON DELETE SET NULL); the caller commits."""
        self.db.execute(
            update(ReportSnapshot)
            .where(ReportSnapshot.definition_id == definition_id)
            .values(definition_id=None)
        )

    def prune(self, definition_id: int, keep: int) -> int:
        """Delete all but the newest ``keep`` snapshots of a definition; returns how many."""
        stale = list(
            self.db.scalars(
                select(ReportSnapshot.id)
                .where(ReportSnapshot.definition_id == definition_id)
                .order_by(ReportSnapshot.generated_at.desc(), ReportSnapshot.id.desc())
                .offset(keep)
            )
        )
        if stale:
            self.db.execute(delete(ReportSnapshot).where(ReportSnapshot.id.in_(stale)))
            self.db.commit()
        return len(stale)

    def delete(self, snapshot: ReportSnapshot) -> None:
        self.db.delete(snapshot)
        self.db.commit()

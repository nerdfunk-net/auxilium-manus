from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, delete, func, or_, select, true
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from core.models.report_data_records import ReportDataRecord

# One retry when an overlapping writer of the same run's collection wins the race.
_REPLACE_ATTEMPTS = 2


class DatasetWriteConflictError(ValueError):
    """Another node of the same run already wrote this dataset for this device."""


class ReportDataRecordRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def replace_rows(
        self,
        *,
        device_name: str,
        dataset: str,
        rows: Sequence[Any],
        run_id: int | None,
        node_id: str | None = None,
    ) -> list[ReportDataRecord]:
        """Write one device's collection for *dataset* in a single transaction.

        With a ``run_id`` the run's earlier collection for the same dataset and device
        is deleted first, so a retried step replaces its rows instead of duplicating
        them. Runless writes always append. An empty *rows* stores one marker row so
        "found nothing" still supersedes an older, non-empty collection. All rows share
        a ``collection_id``; any database error rolls back, leaving the earlier
        collection untouched.

        With a ``run_id`` and a ``node_id``, a collection of the same run, dataset and device that
        another node wrote is not replaced: ``DatasetWriteConflictError`` is raised and nothing
        changes. Rows without a ``node_id`` (older rows, manual writers) never conflict.

        If an overlapping writer of the same run's collection commits between our delete
        and insert, the unique index on (run, dataset, device, position) rejects ours and
        the whole replacement is attempted once more, so exactly one collection survives.
        """
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                return self._replace_once(
                    device_name=device_name,
                    dataset=dataset,
                    rows=rows,
                    run_id=run_id,
                    node_id=node_id,
                )
            except IntegrityError:
                if run_id is None or attempt == _REPLACE_ATTEMPTS - 1:
                    raise
        raise AssertionError("unreachable")  # pragma: no cover

    def _replace_once(
        self,
        *,
        device_name: str,
        dataset: str,
        rows: Sequence[Any],
        run_id: int | None,
        node_id: str | None,
    ) -> list[ReportDataRecord]:
        collection_id = str(uuid.uuid4())
        records = [
            ReportDataRecord(
                device_name=device_name,
                dataset=dataset,
                data=row,
                collection_id=collection_id,
                position=position,
                run_id=run_id,
                node_id=node_id,
            )
            for position, row in enumerate(rows)
        ] or [
            ReportDataRecord(
                device_name=device_name,
                dataset=dataset,
                data={},
                collection_id=collection_id,
                is_empty=True,
                position=0,
                run_id=run_id,
                node_id=node_id,
            )
        ]
        try:
            if run_id is not None:
                # Delete only rows this step may replace (its own or ones without a node), then
                # look for another node's rows that remain. Deleting first closes the window
                # where two writers both pass a check and the later delete removes the earlier
                # writer's committed rows: those survive here and the conflict is raised.
                # Two uncommitted writers collide on the unique (run, dataset, device,
                # position) index instead, and the retry then sees the other's rows.
                replaceable = ReportDataRecord.node_id.is_(None)
                if node_id is not None:
                    replaceable = or_(replaceable, ReportDataRecord.node_id == node_id)
                else:
                    replaceable = true()
                self.db.execute(
                    delete(ReportDataRecord).where(
                        ReportDataRecord.run_id == run_id,
                        ReportDataRecord.dataset == dataset,
                        ReportDataRecord.device_name == device_name,
                        replaceable,
                    )
                )
                self._refuse_other_node(
                    run_id=run_id, dataset=dataset, device_name=device_name, node_id=node_id
                )
            self.db.add_all(records)
            self.db.commit()
        except DatasetWriteConflictError:
            self.db.rollback()
            raise
        except SQLAlchemyError:
            self.db.rollback()
            raise
        return records

    def _refuse_other_node(
        self, *, run_id: int, dataset: str, device_name: str, node_id: str | None
    ) -> None:
        if node_id is None:
            return
        other = self.db.scalar(
            select(ReportDataRecord.node_id)
            .where(
                ReportDataRecord.run_id == run_id,
                ReportDataRecord.dataset == dataset,
                ReportDataRecord.device_name == device_name,
                ReportDataRecord.node_id.is_not(None),
                ReportDataRecord.node_id != node_id,
            )
            .limit(1)
        )
        if other is not None:
            raise DatasetWriteConflictError(
                f"dataset {dataset!r} was already written for this device by step {other!r} in "
                "this run; put all fields of a dataset into one Store for Report step or use "
                "one dataset per step"
            )

    @staticmethod
    def _newest_collection_ids(dataset: str) -> Select[Any]:
        """Select the collection id of each device's newest collection in *dataset*.

        Each device's history is ranked once with a window function; timestamp ties are
        broken by id. Empty-collection markers take part in the ranking, so a device whose
        newest collection found nothing does not fall back to an older one.
        """
        ranked = (
            select(
                ReportDataRecord.collection_id,
                ReportDataRecord.is_empty,
                func.row_number()
                .over(
                    partition_by=ReportDataRecord.device_name,
                    order_by=(ReportDataRecord.created_at.desc(), ReportDataRecord.id.desc()),
                )
                .label("rank"),
            )
            .where(ReportDataRecord.dataset == dataset)
            .subquery()
        )
        return select(ranked.c.collection_id).where(ranked.c.rank == 1)

    @classmethod
    def latest_rows_select(
        cls, dataset: str, *, include_empty: bool = False
    ) -> Select[tuple[ReportDataRecord]]:
        """Every row of each device's newest collection, as a composable select."""
        stmt = select(ReportDataRecord).where(
            ReportDataRecord.dataset == dataset,
            ReportDataRecord.collection_id.in_(cls._newest_collection_ids(dataset)),
        )
        if not include_empty:
            stmt = stmt.where(ReportDataRecord.is_empty.is_(False))
        return stmt

    def latest_per_device(
        self, dataset: str, *, include_empty: bool = False
    ) -> list[ReportDataRecord]:
        """Every row of each device's newest collection in *dataset*.

        A device whose newest collection found no items contributes no rows, unless
        *include_empty* is set: then its marker row (``is_empty``, ``data == {}``) is
        returned, so a caller can tell "zero items" from "never collected". No report query
        does this today (the query compiler leaves markers out, see doc/REPORTS.md, "Known
        limits"); the flag is the tested contract for a future one. Ordered by device name,
        then insertion order. One statement, so one snapshot.
        """
        stmt = self.latest_rows_select(dataset, include_empty=include_empty).order_by(
            ReportDataRecord.device_name, ReportDataRecord.id
        )
        return list(self.db.scalars(stmt))

    def purge_older_than(self, cutoff: datetime, *, batch_size: int = 1000) -> int:
        """Delete rows created before *cutoff*, except each (dataset, device)'s newest collection.

        Whole collections go together (they share ``created_at``), and the newest collection of
        every device and dataset stays however old it is, so "latest" queries keep answering for
        devices that are collected rarely. An empty-collection marker counts as a collection.
        Deletes in batches of *batch_size* rows, committing each, and returns the rows deleted.
        """
        ranked = select(
            ReportDataRecord.collection_id,
            func.row_number()
            .over(
                partition_by=(ReportDataRecord.dataset, ReportDataRecord.device_name),
                order_by=(ReportDataRecord.created_at.desc(), ReportDataRecord.id.desc()),
            )
            .label("rank"),
        ).subquery()
        newest = select(ranked.c.collection_id).where(ranked.c.rank == 1)
        total = 0
        try:
            while True:
                ids = list(
                    self.db.scalars(
                        select(ReportDataRecord.id)
                        .where(
                            ReportDataRecord.created_at < cutoff,
                            ReportDataRecord.collection_id.not_in(newest),
                        )
                        .order_by(ReportDataRecord.id)
                        .limit(batch_size)
                    )
                )
                if not ids:
                    return total
                self.db.execute(delete(ReportDataRecord).where(ReportDataRecord.id.in_(ids)))
                self.db.commit()
                total += len(ids)
        except SQLAlchemyError:
            self.db.rollback()
            raise

    def recent_rows(self, dataset: str, *, limit: int) -> list[ReportDataRecord]:
        """The newest *limit* non-marker rows of *dataset* (a bounded sample, newest first)."""
        stmt = (
            select(ReportDataRecord)
            .where(ReportDataRecord.dataset == dataset, ReportDataRecord.is_empty.is_(False))
            .order_by(ReportDataRecord.id.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def history(
        self,
        *,
        dataset: str,
        device_name: str,
        since: datetime | None = None,
        include_empty: bool = False,
    ) -> list[ReportDataRecord]:
        """One device's rows in *dataset*, oldest first, optionally from *since* on.

        Empty-collection markers are returned only with *include_empty* (not used by the query
        compiler today), which a trend needs to see where a series of items ends.
        """
        stmt = select(ReportDataRecord).where(
            ReportDataRecord.dataset == dataset,
            ReportDataRecord.device_name == device_name,
        )
        if not include_empty:
            stmt = stmt.where(ReportDataRecord.is_empty.is_(False))
        if since is not None:
            stmt = stmt.where(ReportDataRecord.created_at >= since)
        stmt = stmt.order_by(ReportDataRecord.created_at, ReportDataRecord.id)
        return list(self.db.scalars(stmt))

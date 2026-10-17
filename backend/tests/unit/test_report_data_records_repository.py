"""Tests for ReportDataRecordRepository."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from core.models.base import Base
from core.models.report_data_records import ReportDataRecord
from repositories.report_data_records_repository import (
    DatasetWriteConflictError,
    ReportDataRecordRepository,
)


class ReportDataRecordRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        # run_id's FK target is not needed: SQLite does not enforce FKs by default.
        Base.metadata.create_all(engine, tables=[ReportDataRecord.__table__])
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.repo = ReportDataRecordRepository(self.db)

    def _all(self) -> list[ReportDataRecord]:
        return list(self.db.query(ReportDataRecord).order_by(ReportDataRecord.id))

    def _write(
        self,
        rows: list[dict],
        *,
        device: str = "r1",
        dataset: str = "inv",
        run_id: int | None = None,
    ) -> None:
        self.repo.replace_rows(device_name=device, dataset=dataset, rows=rows, run_id=run_id)

    # --- writing -----------------------------------------------------------------

    def test_runless_writes_always_append(self) -> None:
        self._write([{"serial": "A"}])
        self._write([{"serial": "A"}])

        rows = self._all()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.run_id is None for row in rows))

    def test_writes_in_different_runs_append(self) -> None:
        self._write([{"serial": "A"}], run_id=1)
        self._write([{"serial": "A"}], run_id=2)

        self.assertEqual([row.run_id for row in self._all()], [1, 2])

    def test_rows_of_one_write_share_a_collection_id(self) -> None:
        self._write([{"n": 1}, {"n": 2}])
        self._write([{"n": 3}])

        first, second, third = self._all()
        self.assertEqual(first.collection_id, second.collection_id)
        self.assertNotEqual(first.collection_id, third.collection_id)

    def test_same_run_dataset_device_replaces_the_earlier_collection(self) -> None:
        self._write([{"n": 1}, {"n": 2}, {"n": 3}], run_id=1)
        self._write([{"n": 9}], run_id=1)

        self.assertEqual([row.data for row in self._all()], [{"n": 9}])

    def test_replacement_leaves_other_datasets_devices_and_runs_alone(self) -> None:
        self._write([{"a": 1}], run_id=1)
        self._write([{"a": 1}], run_id=1, dataset="other")
        self._write([{"a": 1}], run_id=1, device="r2")
        self._write([{"a": 1}], run_id=2)

        self._write([{"a": 2}], run_id=1)

        self.assertEqual(len(self._all()), 4)
        self.assertEqual(sorted(row.data["a"] for row in self._all()), [1, 1, 1, 2])

    def test_empty_rows_store_a_marker(self) -> None:
        self._write([])

        (marker,) = self._all()
        self.assertTrue(marker.is_empty)
        self.assertEqual(marker.data, {})

    def test_commit_failure_rolls_back_so_session_stays_usable(self) -> None:
        real_commit = self.db.commit
        calls = {"n": 0}

        def failing_commit() -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise OperationalError("COMMIT", {}, Exception("connection dropped"))
            real_commit()

        self.db.commit = failing_commit  # type: ignore[method-assign]
        with self.assertRaises(OperationalError):
            self._write([{"a": 1}])

        # The failed transaction was rolled back: the next write succeeds.
        self._write([{"a": 2}], device="r2")
        self.assertEqual([row.device_name for row in self._all()], ["r2"])

    def test_failed_replacement_keeps_the_earlier_collection(self) -> None:
        self._write([{"n": 1}], run_id=1)
        real_commit = self.db.commit

        def failing_commit() -> None:
            raise OperationalError("COMMIT", {}, Exception("connection dropped"))

        self.db.commit = failing_commit  # type: ignore[method-assign]
        with self.assertRaises(OperationalError):
            self._write([{"n": 2}], run_id=1)
        self.db.commit = real_commit  # type: ignore[method-assign]

        self.assertEqual([row.data for row in self._all()], [{"n": 1}])

    def test_rows_get_their_position_in_the_collection(self) -> None:
        self._write([{"n": "a"}, {"n": "b"}, {"n": "c"}])
        self.assertEqual([row.position for row in self._all()], [0, 1, 2])

    def test_duplicate_run_collection_is_a_unique_violation(self) -> None:
        # Two overlapping writers for the same run/dataset/device would both insert
        # position 0; the database must refuse the second one.
        self._write([{"n": 1}], run_id=1)
        self.db.add(
            ReportDataRecord(
                device_name="r1",
                dataset="inv",
                data={"n": 2},
                collection_id="other",
                position=0,
                run_id=1,
            )
        )
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_integrity_error_on_insert_is_retried_once_as_a_replacement(self) -> None:
        self._write([{"n": 1}], run_id=1)
        real_add_all = self.db.add_all
        calls = {"n": 0}

        def conflicting_add_all(records) -> None:  # type: ignore[no-untyped-def]
            calls["n"] += 1
            if calls["n"] == 1:
                # A concurrent writer committed its collection after our delete.
                other = ReportDataRecord(
                    device_name="r1",
                    dataset="inv",
                    data={"n": "rival"},
                    collection_id="rival",
                    position=0,
                    run_id=1,
                )
                real_add_all([other, *records])
                return
            real_add_all(records)

        self.db.add_all = conflicting_add_all  # type: ignore[method-assign]
        self._write([{"n": 2}], run_id=1)

        self.assertEqual([row.data for row in self._all()], [{"n": 2}])

    # --- reading -----------------------------------------------------------------

    def _add(
        self,
        device: str,
        dataset: str,
        data: dict,
        created_at: datetime,
        *,
        collection_id: str,
        is_empty: bool = False,
    ) -> None:
        self.db.add(
            ReportDataRecord(
                device_name=device,
                dataset=dataset,
                data=data,
                created_at=created_at,
                collection_id=collection_id,
                is_empty=is_empty,
            )
        )
        self.db.commit()

    # --- same dataset written by two nodes -----------------------------------------

    def test_another_node_writing_the_same_dataset_and_device_in_a_run_is_refused(self) -> None:
        self.repo.replace_rows(
            device_name="r1", dataset="inv", rows=[{"a": 1}], run_id=1, node_id="n1"
        )

        with self.assertRaises(DatasetWriteConflictError) as ctx:
            self.repo.replace_rows(
                device_name="r1", dataset="inv", rows=[{"b": 2}], run_id=1, node_id="n2"
            )

        self.assertIn("n1", str(ctx.exception))
        self.assertEqual([row.data for row in self._all()], [{"a": 1}])

    def test_the_same_node_replaces_its_own_earlier_collection(self) -> None:
        for value in (1, 2):
            self.repo.replace_rows(
                device_name="r1", dataset="inv", rows=[{"a": value}], run_id=1, node_id="n1"
            )

        self.assertEqual([row.data for row in self._all()], [{"a": 2}])

    def test_different_nodes_may_write_different_devices_datasets_or_runs(self) -> None:
        write = self.repo.replace_rows
        write(device_name="r1", dataset="inv", rows=[{"a": 1}], run_id=1, node_id="n1")
        write(device_name="r2", dataset="inv", rows=[{"a": 1}], run_id=1, node_id="n2")
        write(device_name="r1", dataset="other", rows=[{"a": 1}], run_id=1, node_id="n2")
        write(device_name="r1", dataset="inv", rows=[{"a": 1}], run_id=2, node_id="n2")

        self.assertEqual(len(self._all()), 4)

    def test_rows_without_a_node_id_never_conflict(self) -> None:
        self.repo.replace_rows(device_name="r1", dataset="inv", rows=[{"a": 1}], run_id=1)
        self.repo.replace_rows(
            device_name="r1", dataset="inv", rows=[{"a": 2}], run_id=1, node_id="n2"
        )

        self.assertEqual([row.data for row in self._all()], [{"a": 2}])
        self.assertEqual(self._all()[0].node_id, "n2")

    # --- retention ---------------------------------------------------------------

    def test_purge_deletes_old_collections_but_keeps_newest_per_device_and_dataset(self) -> None:
        now = datetime(2026, 1, 10, tzinfo=UTC)
        cutoff = now - timedelta(days=30)
        old = now - timedelta(days=60)
        self._add("r1", "inv", {"v": "old"}, old, collection_id="c1")
        self._add("r1", "inv", {"v": "old2"}, old + timedelta(days=1), collection_id="c2")
        self._add("r1", "inv", {"v": "new"}, now, collection_id="c3")
        # r2's only collection is old: it is still its newest, so it stays.
        self._add("r2", "inv", {"v": "stale"}, old, collection_id="c4")
        self._add("r1", "other", {"v": "x"}, old, collection_id="c5")

        deleted = self.repo.purge_older_than(cutoff, batch_size=2)

        self.assertEqual(deleted, 2)
        self.assertEqual({row.collection_id for row in self._all()}, {"c3", "c4", "c5"})

    def test_purge_removes_all_rows_of_an_old_multi_row_collection(self) -> None:
        now = datetime(2026, 1, 10, tzinfo=UTC)
        old = now - timedelta(days=60)
        for n in range(3):
            self._add("r1", "inv", {"n": n}, old, collection_id="c1")
        self._add("r1", "inv", {"n": 9}, now, collection_id="c2")

        self.assertEqual(self.repo.purge_older_than(now - timedelta(days=30)), 3)
        self.assertEqual([row.collection_id for row in self._all()], ["c2"])

    def test_purge_keeps_an_empty_marker_that_is_the_newest(self) -> None:
        now = datetime(2026, 1, 10, tzinfo=UTC)
        old = now - timedelta(days=60)
        self._add("r1", "inv", {"v": 1}, old, collection_id="c1")
        self._add("r1", "inv", {}, old + timedelta(days=1), collection_id="c2", is_empty=True)

        self.assertEqual(self.repo.purge_older_than(now - timedelta(days=30)), 1)
        self.assertEqual([row.collection_id for row in self._all()], ["c2"])

    def test_purge_nothing_older_than_cutoff(self) -> None:
        now = datetime(2026, 1, 10, tzinfo=UTC)
        self._add("r1", "inv", {"v": 1}, now, collection_id="c1")

        self.assertEqual(self.repo.purge_older_than(now - timedelta(days=30)), 0)
        self.assertEqual(len(self._all()), 1)

    def test_latest_per_device_returns_newest_collection_per_device(self) -> None:
        now = datetime(2026, 1, 10, tzinfo=UTC)
        self._add("r1", "inv", {"v": "old"}, now - timedelta(days=2), collection_id="c1")
        self._add("r1", "inv", {"v": "new"}, now, collection_id="c2")
        self._add("r2", "inv", {"v": "only"}, now - timedelta(days=1), collection_id="c3")
        self._add("r3", "other", {"v": "x"}, now, collection_id="c4")

        latest = self.repo.latest_per_device("inv")

        self.assertEqual(
            {row.device_name: row.data["v"] for row in latest}, {"r1": "new", "r2": "only"}
        )

    def test_latest_per_device_returns_every_row_of_an_item_collection(self) -> None:
        now = datetime(2026, 1, 10, tzinfo=UTC)
        self._add("r1", "ifaces", {"n": "old"}, now - timedelta(days=1), collection_id="c1")
        self._add("r1", "ifaces", {"n": "Gi1"}, now, collection_id="c2")
        self._add("r1", "ifaces", {"n": "Gi2"}, now, collection_id="c2")

        latest = self.repo.latest_per_device("ifaces")

        self.assertEqual([row.data["n"] for row in latest], ["Gi1", "Gi2"])

    def test_latest_empty_collection_hides_older_items(self) -> None:
        now = datetime(2026, 1, 10, tzinfo=UTC)
        self._add("r1", "ntp", {"a": "10.0.0.1"}, now - timedelta(days=1), collection_id="c1")
        self._add("r1", "ntp", {}, now, collection_id="c2", is_empty=True)
        self._add("r2", "ntp", {"a": "10.0.0.2"}, now, collection_id="c3")

        latest = self.repo.latest_per_device("ntp")

        self.assertEqual([row.device_name for row in latest], ["r2"])

    def test_latest_breaks_timestamp_ties_by_id(self) -> None:
        same = datetime(2026, 1, 10, tzinfo=UTC)
        self._add("r1", "inv", {"v": "first"}, same, collection_id="c1")
        self._add("r1", "inv", {"v": "second"}, same, collection_id="c2")

        latest = self.repo.latest_per_device("inv")

        self.assertEqual([row.data["v"] for row in latest], ["second"])

    def test_history_is_ordered_oldest_first_filtered_and_skips_markers(self) -> None:
        now = datetime(2026, 1, 10, tzinfo=UTC)
        self._add("r1", "inv", {"v": 2}, now, collection_id="c1")
        self._add("r1", "inv", {"v": 1}, now - timedelta(days=3), collection_id="c2")
        self._add("r1", "inv", {"v": 0}, now - timedelta(days=30), collection_id="c3")
        self._add("r1", "inv", {}, now - timedelta(days=1), collection_id="c4", is_empty=True)
        self._add("r2", "inv", {"v": 9}, now, collection_id="c5")

        rows = self.repo.history(dataset="inv", device_name="r1", since=now - timedelta(days=7))

        self.assertEqual([row.data["v"] for row in rows], [1, 2])

    def test_history_without_since_returns_everything(self) -> None:
        now = datetime(2026, 1, 10, tzinfo=UTC)
        self._add("r1", "inv", {"v": 1}, now - timedelta(days=30), collection_id="c1")
        self._add("r1", "inv", {"v": 2}, now, collection_id="c2")

        rows = self.repo.history(dataset="inv", device_name="r1")

        self.assertEqual(len(rows), 2)

    def test_include_empty_exposes_zero_item_collections(self) -> None:
        now = datetime(2026, 1, 10, tzinfo=UTC)
        self._add("r1", "ntp", {"a": "10.0.0.1"}, now - timedelta(days=1), collection_id="c1")
        self._add("r1", "ntp", {}, now, collection_id="c2", is_empty=True)
        self._add("r2", "ntp", {"a": "10.0.0.2"}, now, collection_id="c3")

        latest = self.repo.latest_per_device("ntp", include_empty=True)

        self.assertEqual(
            [(row.device_name, row.is_empty) for row in latest], [("r1", True), ("r2", False)]
        )

    def test_history_include_empty_shows_the_series_end(self) -> None:
        now = datetime(2026, 1, 10, tzinfo=UTC)
        self._add("r1", "ntp", {"a": "x"}, now - timedelta(days=1), collection_id="c1")
        self._add("r1", "ntp", {}, now, collection_id="c2", is_empty=True)

        rows = self.repo.history(dataset="ntp", device_name="r1", include_empty=True)

        self.assertEqual([row.is_empty for row in rows], [False, True])

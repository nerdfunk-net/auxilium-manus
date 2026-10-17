"""Tests for the report definition and snapshot repositories."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from core.models.base import Base
from core.models.report_definitions import ReportDefinition
from core.models.report_snapshots import ReportSnapshot
from repositories.report_definitions_repository import ReportDefinitionsRepository
from repositories.report_snapshots_repository import ReportSnapshotsRepository


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine, tables=[ReportDefinition.__table__, ReportSnapshot.__table__]
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.defs = ReportDefinitionsRepository(self.db)
        self.snaps = ReportSnapshotsRepository(self.db)


class DefinitionsRepositoryTests(_Base):
    def test_create_get_and_list_ordered_by_name(self) -> None:
        b = self.defs.create(name="b", description=None, sections=[], created_by=None)
        self.defs.create(name="a", description="d", sections=[{"id": "x"}], created_by=None)

        self.assertEqual(self.defs.get(b.id).name, "b")  # type: ignore[union-attr]
        self.assertIsNone(self.defs.get(999))
        self.assertEqual([d.name for d in self.defs.list_all()], ["a", "b"])
        self.assertEqual(self.defs.get_by_name("a").sections, [{"id": "x"}])  # type: ignore[union-attr]

    def test_name_is_unique(self) -> None:
        self.defs.create(name="a", description=None, sections=[], created_by=None)
        with self.assertRaises(IntegrityError):
            self.defs.create(name="a", description=None, sections=[], created_by=None)

    def test_update_is_whitelisted(self) -> None:
        d = self.defs.create(name="a", description=None, sections=[], created_by=None)
        updated = self.defs.update(d, name="z", sections=[{"id": "s"}])
        self.assertEqual((updated.name, updated.sections), ("z", [{"id": "s"}]))
        with self.assertRaises(ValueError):
            self.defs.update(d, id=5)

    def test_delete(self) -> None:
        d = self.defs.create(name="a", description=None, sections=[], created_by=None)
        self.defs.delete(d)
        self.assertIsNone(self.defs.get(d.id))


class SnapshotsRepositoryTests(_Base):
    def _snap(self, definition_id: int | None, name: str = "s") -> ReportSnapshot:
        return self.snaps.create(
            definition_id=definition_id,
            name=name,
            generated_by="u",
            status="complete",
            content={"name": name, "description": None, "sections": []},
        )

    def test_list_filters_by_definition_newest_first(self) -> None:
        d = self.defs.create(name="a", description=None, sections=[], created_by=None)
        first = self._snap(d.id, "first")
        second = self._snap(d.id, "second")
        self._snap(None, "orphan")

        listed = self.snaps.list_snapshots(definition_id=d.id)
        self.assertEqual([s.id for s in listed], [second.id, first.id])
        self.assertEqual(len(self.snaps.list_snapshots()), 3)
        self.assertEqual(len(self.snaps.list_snapshots(limit=1)), 1)

    def test_stats_per_definition(self) -> None:
        d = self.defs.create(name="a", description=None, sections=[], created_by=None)
        e = self.defs.create(name="b", description=None, sections=[], created_by=None)
        self._snap(d.id)
        self._snap(d.id)

        stats = self.snaps.stats_by_definition()
        self.assertEqual(stats[d.id][0], 2)
        self.assertIsNotNone(stats[d.id][1])
        self.assertNotIn(e.id, stats)

    def test_get_and_delete(self) -> None:
        s = self._snap(None)
        self.assertEqual(self.snaps.get(s.id).name, "s")  # type: ignore[union-attr]
        self.snaps.delete(s)
        self.assertIsNone(self.snaps.get(s.id))

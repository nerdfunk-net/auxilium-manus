"""TemplatesService CRUD: the Markdown `notes` (wiki) field round-trips through
create/update/get, and update only touches fields that were provided."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.models.credentials import Credential
from core.models.templates import Template
from core.models.users import User
from services.templates.templates_service import TemplatesService


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    User.metadata.create_all(
        engine, tables=[User.__table__, Credential.__table__, Template.__table__]
    )
    return sessionmaker(bind=engine)()


def _make_user(db: Session, username: str) -> User:
    user = User(username=username, password_hash="hash", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TemplatesServiceCrudTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _make_session()
        self.addCleanup(self.db.get_bind().dispose)
        self.addCleanup(self.db.close)
        self.user = _make_user(self.db, "user1")
        self.service = TemplatesService(self.db)

    def _create(self, *, name: str, notes: str | None) -> dict:
        return self.service.create_template(
            name=name,
            description=None,
            notes=notes,
            template_type="jinja2",
            category="netmiko",
            content="",
            variables={},
            pre_run_commands=None,
            pre_run_use_textfsm=False,
            nautobot_attributes=None,
            credential_id=None,
            created_by="user1",
            acting_user_id=self.user.id,
        )

    def test_create_persists_and_returns_notes(self) -> None:
        created = self._create(name="tpl-notes", notes="# Docs\nbody")
        self.assertEqual(created["notes"], "# Docs\nbody")

        fetched = self.service.get_template(created["id"])
        self.assertEqual(fetched["notes"], "# Docs\nbody")

    def test_create_defaults_notes_to_none(self) -> None:
        created = self._create(name="tpl-plain", notes=None)
        self.assertIsNone(created["notes"])

    def test_update_sets_notes(self) -> None:
        created = self._create(name="tpl-upd", notes=None)

        updated = self.service.update_template(
            created["id"],
            notes="updated docs",
            acting_user_id=self.user.id,
        )
        self.assertEqual(updated["notes"], "updated docs")

    def test_update_without_notes_leaves_existing(self) -> None:
        created = self._create(name="tpl-keep", notes="keep me")

        updated = self.service.update_template(
            created["id"],
            name="tpl-keep-renamed",
            acting_user_id=self.user.id,
        )
        self.assertEqual(updated["notes"], "keep me")

    def test_update_can_clear_notes_with_empty_string(self) -> None:
        created = self._create(name="tpl-clear", notes="to be cleared")

        updated = self.service.update_template(
            created["id"],
            notes="",
            acting_user_id=self.user.id,
        )
        self.assertEqual(updated["notes"], "")


if __name__ == "__main__":
    unittest.main()

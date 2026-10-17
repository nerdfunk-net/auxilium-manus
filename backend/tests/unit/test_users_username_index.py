"""Case-variant usernames are rejected by the database too (S1-18)."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.models.users import User


def _user(username: str) -> User:
    return User(username=username, password_hash="x")


class UsernameLowerIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        User.__table__.create(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_case_variant_username_is_rejected_by_the_database(self) -> None:
        with Session(self.engine) as session:
            session.add(_user("Admin"))
            session.commit()
            session.add(_user("admin"))
            with self.assertRaises(IntegrityError):
                session.commit()

    def test_distinct_usernames_are_accepted(self) -> None:
        with Session(self.engine) as session:
            session.add_all([_user("alice"), _user("bob")])
            session.commit()
            self.assertEqual(session.query(User).count(), 2)

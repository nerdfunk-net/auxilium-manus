"""scripts/link_oidc_identity.py: bind a local user to an IdP identity (T6)."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.users import User

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "link_oidc_identity.py"
_spec = importlib.util.spec_from_file_location("link_oidc_identity", _SCRIPT)
link = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(link)


class LinkOidcIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        User.metadata.create_all(engine, tables=[User.__table__])
        self.addCleanup(engine.dispose)
        self.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        with self.session_factory() as db:
            db.add_all(
                [
                    User(username="alice", password_hash="h", is_active=True),
                    User(username="bob", password_hash="h", is_active=True),
                ]
            )
            db.commit()
        patcher = patch.object(link, "SessionLocal", self.session_factory)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _user(self, username: str) -> User:
        with self.session_factory() as db:
            return db.query(User).filter_by(username=username).one()

    def test_links_and_ends_existing_sessions(self) -> None:
        before = self._user("alice").token_version
        self.assertEqual(link.main("alice", "okta", "sub-1"), 0)
        alice = self._user("alice")
        self.assertEqual((alice.oidc_provider, alice.oidc_subject), ("okta", "sub-1"))
        self.assertEqual(alice.token_version, before + 1)

    def test_refuses_an_identity_bound_to_another_user(self) -> None:
        self.assertEqual(link.main("alice", "okta", "sub-1"), 0)
        self.assertEqual(link.main("bob", "okta", "sub-1"), 1)
        self.assertIsNone(self._user("bob").oidc_subject)

    def test_relinking_the_same_user_is_allowed(self) -> None:
        self.assertEqual(link.main("alice", "okta", "sub-1"), 0)
        self.assertEqual(link.main("alice", "okta", "sub-1"), 0)

    def test_refuses_an_unknown_user(self) -> None:
        self.assertEqual(link.main("nobody", "okta", "sub-1"), 1)

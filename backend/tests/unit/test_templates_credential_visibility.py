"""TemplatesService must not let a template be wired to another user's
private credential (M12) — see services/templates/templates_service.py
::TemplatesService._assert_credential_visible."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.models.credentials import Credential
from core.models.templates import Template
from core.models.users import User
from services.credentials.credentials_service import CredentialsService
from services.templates.exceptions import TemplateCredentialNotFoundError
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


class TemplateCredentialVisibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _make_session()
        self.user1 = _make_user(self.db, "user1")
        self.user2 = _make_user(self.db, "user2")
        self.service = TemplatesService(self.db)

    def test_private_credential_of_other_user_is_not_visible(self) -> None:
        credential = CredentialsService(self.db).create_credential(
            name="owned-by-user2",
            username="admin",
            cred_type="generic",
            password="secret",
            visibility="private",
            acting_user_id=self.user2.id,
        )

        with self.assertRaises(TemplateCredentialNotFoundError):
            self.service.create_template(
                name="tpl-1",
                description=None,
                template_type="jinja2",
                category="netmiko",
                content="",
                variables={},
                pre_run_commands=None,
                pre_run_use_textfsm=False,
                nautobot_attributes=None,
                credential_id=credential["id"],
                created_by="user1",
                acting_user_id=self.user1.id,
            )

    def test_own_private_credential_is_visible(self) -> None:
        credential = CredentialsService(self.db).create_credential(
            name="owned-by-user1",
            username="admin",
            cred_type="generic",
            password="secret",
            visibility="private",
            acting_user_id=self.user1.id,
        )

        result = self.service.create_template(
            name="tpl-2",
            description=None,
            template_type="jinja2",
            category="netmiko",
            content="",
            variables={},
            pre_run_commands=None,
            pre_run_use_textfsm=False,
            nautobot_attributes=None,
            credential_id=credential["id"],
            created_by="user1",
            acting_user_id=self.user1.id,
        )
        self.assertEqual(result["credential_id"], credential["id"])


if __name__ == "__main__":
    unittest.main()

"""The "report" template category: Jinja2 only, none of the device-oriented options."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.models.credentials import Credential
from core.models.templates import Template
from core.models.users import User
from services.templates.categories import CATEGORY_NETMIKO, CATEGORY_REPORT
from services.templates.exceptions import TemplateValidationError
from services.templates.templates_service import TemplatesService


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    User.metadata.create_all(
        engine, tables=[User.__table__, Credential.__table__, Template.__table__]
    )
    return sessionmaker(bind=engine)()


class ReportCategoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _session()
        self.addCleanup(self.db.get_bind().dispose)
        self.addCleanup(self.db.close)
        user = User(username="u", password_hash="h", is_active=True)
        self.db.add(user)
        self.db.commit()
        self.user_id = user.id
        self.service = TemplatesService(self.db)

    def _create(self, name: str = "t", **overrides):
        values = {
            "name": name,
            "description": None,
            "notes": None,
            "template_type": "jinja2",
            "category": CATEGORY_REPORT,
            "content": "# {{ report.name }}",
            "variables": {},
            "pre_run_commands": None,
            "pre_run_use_textfsm": False,
            "nautobot_attributes": None,
            "credential_id": None,
            "created_by": "u",
            "acting_user_id": self.user_id,
        }
        values.update(overrides)
        return self.service.create_template(**values)

    def test_a_plain_jinja_report_template_is_accepted(self) -> None:
        created = self._create()

        self.assertEqual(created["category"], "report")
        self.assertEqual([t["name"] for t in self.service.list_templates(category="report")], ["t"])
        self.assertEqual(self.service.list_templates(category=CATEGORY_NETMIKO), [])

    def test_only_jinja2_is_allowed(self) -> None:
        for template_type in ("text", "textfsm"):
            with self.assertRaises(TemplateValidationError):
                self._create(template_type=template_type)

    def test_device_options_are_rejected(self) -> None:
        for override in (
            {"pre_run_commands": ["show version"]},
            {"pre_run_use_textfsm": True},
            {"nautobot_attributes": ["interfaces"]},
            {"batfish_config": {"enabled": True}},
        ):
            with self.subTest(override=override), self.assertRaises(TemplateValidationError):
                self._create(**override)

    def test_other_categories_are_not_restricted(self) -> None:
        created = self._create(
            "n", category=CATEGORY_NETMIKO, template_type="textfsm", pre_run_commands=["x"]
        )

        self.assertEqual(created["template_type"], "textfsm")

    def test_update_checks_the_resulting_template(self) -> None:
        netmiko = self._create("n", category=CATEGORY_NETMIKO, pre_run_commands=["show x"])
        with self.assertRaises(TemplateValidationError):
            self.service.update_template(
                netmiko["id"], category=CATEGORY_REPORT, acting_user_id=self.user_id
            )

        report = self._create("r")
        with self.assertRaises(TemplateValidationError):
            self.service.update_template(
                report["id"], template_type="text", acting_user_id=self.user_id
            )
        with self.assertRaises(TemplateValidationError):
            self.service.update_template(
                report["id"], pre_run_commands=["show x"], acting_user_id=self.user_id
            )
        updated = self.service.update_template(
            report["id"], content="new", acting_user_id=self.user_id
        )
        self.assertEqual(updated["content"], "new")


class CategoryChangeTests(ReportCategoryTests):
    def test_a_template_cannot_move_into_or_out_of_the_report_category(self) -> None:
        report = self._create("r")
        netmiko = self._create("n", category=CATEGORY_NETMIKO)

        with self.assertRaises(TemplateValidationError):
            self.service.update_template(
                report["id"], category=CATEGORY_NETMIKO, acting_user_id=self.user_id
            )
        with self.assertRaises(TemplateValidationError):
            self.service.update_template(
                netmiko["id"], category=CATEGORY_REPORT, acting_user_id=self.user_id
            )
        # sending the category it already has is fine
        same = self.service.update_template(
            report["id"], category=CATEGORY_REPORT, content="x", acting_user_id=self.user_id
        )
        self.assertEqual(same["content"], "x")

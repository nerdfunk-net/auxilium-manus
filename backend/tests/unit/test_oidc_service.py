"""Tests for OIDCService: claim extraction, CA cert path resolution, and the
user-provisioning role-fallback behavior (no real network calls)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import PROJECT_ROOT
from core.models.rbac import Permission, Role, RolePermission, UserPermission, UserRole
from core.models.users import User
from services.auth.oidc_service import (
    OIDCApprovalPendingError,
    OIDCAutoProvisioningDisabledError,
    OIDCError,
    OIDCIdentityConflictError,
    OIDCService,
)


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    User.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Role.__table__,
            Permission.__table__,
            RolePermission.__table__,
            UserRole.__table__,
            UserPermission.__table__,
        ],
    )
    return sessionmaker(bind=engine)()


def _make_service(provider_config: dict) -> OIDCService:
    config_service = MagicMock()
    config_service.get_provider.return_value = {
        "provider_id": "corporate",
        "enabled": True,
        **provider_config,
    }
    return OIDCService(config_service)


class ExtractUserDataTests(unittest.TestCase):
    def test_uses_default_claim_mappings(self) -> None:
        service = _make_service({})

        result = service.extract_user_data(
            "corporate",
            {
                "preferred_username": "jdoe",
                "email": "jdoe@example.com",
                "name": "Jane Doe",
                "sub": "abc123",
            },
        )

        self.assertEqual(result["username"], "jdoe")
        self.assertEqual(result["email"], "jdoe@example.com")
        self.assertEqual(result["display_name"], "Jane Doe")
        self.assertEqual(result["sub"], "abc123")

    def test_uses_custom_claim_mappings(self) -> None:
        service = _make_service({"claim_mappings": {"username": "email"}})

        result = service.extract_user_data(
            "corporate", {"email": "jdoe@example.com", "sub": "abc123"}
        )

        self.assertEqual(result["username"], "jdoe@example.com")

    def test_missing_username_claim_raises(self) -> None:
        service = _make_service({})

        with self.assertRaises(OIDCError):
            service.extract_user_data("corporate", {"email": "jdoe@example.com"})

    def test_unknown_provider_raises(self) -> None:
        config_service = MagicMock()
        config_service.get_provider.return_value = None
        service = OIDCService(config_service)

        with self.assertRaises(OIDCError):
            service.extract_user_data("ghost", {})

    def test_missing_sub_claim_raises(self) -> None:
        service = _make_service({})

        with self.assertRaises(OIDCError):
            service.extract_user_data(
                "corporate", {"preferred_username": "jdoe", "email": "jdoe@example.com"}
            )


class ResolveCaCertPathTests(unittest.TestCase):
    def test_relative_path_resolves_against_project_root(self) -> None:
        service = _make_service({})

        resolved = service.resolve_ca_cert_path("config/certs/corporate-ca.crt")

        self.assertEqual(resolved, PROJECT_ROOT / "config" / "certs" / "corporate-ca.crt")

    def test_absolute_path_is_returned_unchanged(self) -> None:
        service = _make_service({})

        resolved = service.resolve_ca_cert_path("/etc/ssl/certs/ca.crt")

        self.assertEqual(str(resolved), "/etc/ssl/certs/ca.crt")


class ProvisionOrGetUserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _make_session()
        self.addCleanup(self.db.get_bind().dispose)
        self.addCleanup(self.db.close)
        self.viewer_role = Role(name="viewer", is_system=True)
        self.admin_role = Role(name="admin", is_system=True)
        self.db.add_all([self.viewer_role, self.admin_role])
        self.db.commit()

    def _user_data(self, **overrides) -> dict:
        base = {
            "username": "jdoe",
            "email": "jdoe@example.com",
            "display_name": "Jane Doe",
            "sub": "abc123",
            "provider_id": "corporate",
        }
        base.update(overrides)
        return base

    def test_new_user_created_inactive_and_pending_approval(self) -> None:
        service = _make_service({"default_role": "viewer"})

        with self.assertRaises(OIDCApprovalPendingError) as ctx:
            service.provision_or_get_user("corporate", self._user_data(), self.db)

        self.assertEqual(ctx.exception.username, "jdoe")
        user = self.db.query(User).filter_by(username="jdoe").one()
        self.assertFalse(user.is_active)
        self.assertEqual(user.oidc_provider, "corporate")
        self.assertEqual(user.oidc_subject, "abc123")
        self.assertEqual(user.email, "jdoe@example.com")
        roles = self.db.query(UserRole).filter_by(user_id=user.id).all()
        self.assertEqual([r.role_id for r in roles], [self.viewer_role.id])

    def test_invalid_default_role_falls_back_to_viewer(self) -> None:
        service = _make_service({"default_role": "does-not-exist"})

        with self.assertRaises(OIDCApprovalPendingError):
            service.provision_or_get_user("corporate", self._user_data(), self.db)

        user = self.db.query(User).filter_by(username="jdoe").one()
        roles = self.db.query(UserRole).filter_by(user_id=user.id).all()
        self.assertEqual([r.role_id for r in roles], [self.viewer_role.id])

    def test_auto_provision_disabled_raises_for_new_user(self) -> None:
        service = _make_service({"auto_provision": False})

        with self.assertRaises(OIDCAutoProvisioningDisabledError):
            service.provision_or_get_user("corporate", self._user_data(), self.db)

        self.assertIsNone(self.db.query(User).filter_by(username="jdoe").one_or_none())

    def test_existing_user_matched_by_provider_and_subject_is_returned(self) -> None:
        existing = User(
            username="jdoe",
            password_hash="hash",
            is_active=True,
            email="old@example.com",
            oidc_provider="corporate",
            oidc_subject="abc123",
        )
        self.db.add(existing)
        self.db.commit()
        service = _make_service({})

        result = service.provision_or_get_user("corporate", self._user_data(), self.db)

        self.assertEqual(result.id, existing.id)
        self.assertEqual(result.email, "jdoe@example.com")
        self.assertEqual(result.oidc_provider, "corporate")
        self.assertEqual(result.oidc_subject, "abc123")

    def test_existing_inactive_user_matched_by_identity_raises_pending_approval(self) -> None:
        existing = User(
            username="jdoe",
            password_hash="hash",
            is_active=False,
            oidc_provider="corporate",
            oidc_subject="abc123",
        )
        self.db.add(existing)
        self.db.commit()
        service = _make_service({})

        with self.assertRaises(OIDCApprovalPendingError):
            service.provision_or_get_user("corporate", self._user_data(), self.db)

    def test_username_collision_with_local_account_raises_conflict(self) -> None:
        # Local account, never touched OIDC: oidc_provider is None.
        local_admin = User(username="jdoe", password_hash="hash", is_active=True)
        self.db.add(local_admin)
        self.db.commit()
        service = _make_service({})

        with self.assertRaises(OIDCIdentityConflictError):
            service.provision_or_get_user("corporate", self._user_data(), self.db)

        self.db.refresh(local_admin)
        self.assertIsNone(local_admin.oidc_provider)
        self.assertIsNone(local_admin.oidc_subject)

    def test_username_collision_with_other_provider_raises_conflict(self) -> None:
        other_provider_user = User(
            username="jdoe",
            password_hash="hash",
            is_active=True,
            oidc_provider="other-idp",
            oidc_subject="abc123",
        )
        self.db.add(other_provider_user)
        self.db.commit()
        service = _make_service({})

        with self.assertRaises(OIDCIdentityConflictError):
            service.provision_or_get_user("corporate", self._user_data(), self.db)

    def test_same_provider_different_subject_raises_conflict(self) -> None:
        different_subject_user = User(
            username="jdoe",
            password_hash="hash",
            is_active=True,
            oidc_provider="corporate",
            oidc_subject="someone-else",
        )
        self.db.add(different_subject_user)
        self.db.commit()
        service = _make_service({})

        with self.assertRaises(OIDCIdentityConflictError):
            service.provision_or_get_user("corporate", self._user_data(), self.db)

    def test_profile_sync_never_changes_username_or_identity(self) -> None:
        existing = User(
            username="jdoe",
            password_hash="hash",
            is_active=True,
            email="old@example.com",
            display_name="Old Name",
            oidc_provider="corporate",
            oidc_subject="abc123",
        )
        self.db.add(existing)
        self.db.commit()
        service = _make_service({})

        result = service.provision_or_get_user(
            "corporate",
            self._user_data(email="new@example.com", display_name="New Name"),
            self.db,
        )

        self.assertEqual(result.username, "jdoe")
        self.assertEqual(result.oidc_provider, "corporate")
        self.assertEqual(result.oidc_subject, "abc123")
        self.assertEqual(result.email, "new@example.com")
        self.assertEqual(result.display_name, "New Name")

    def test_new_user_is_created_with_subject(self) -> None:
        service = _make_service({"default_role": "viewer"})

        with self.assertRaises(OIDCApprovalPendingError):
            service.provision_or_get_user("corporate", self._user_data(), self.db)

        user = self.db.query(User).filter_by(username="jdoe").one()
        self.assertEqual(user.oidc_provider, "corporate")
        self.assertEqual(user.oidc_subject, "abc123")

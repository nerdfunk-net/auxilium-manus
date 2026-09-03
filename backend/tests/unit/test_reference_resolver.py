"""Tests for services.execution.reference_resolver."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.execution.reference_resolver import (
    ReferenceValidationError,
    validate_reference_inputs,
)


def _cred(name: str, *, cred_type: str = "ssh", status: str = "active", visibility: str = "global"):
    return {"name": name, "type": cred_type, "status": status, "visibility": visibility}


class InventoryReferenceResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        svc_patch = patch("services.sources.nautobot.persistence_service.InventoryService")
        repo_patch = patch("repositories.inventory_repository.InventoryRepository")
        user_patch = patch("repositories.user_repository.UserRepository")
        self.inv_service = svc_patch.start().return_value
        repo_patch.start()
        self.user_repo = user_patch.start().return_value
        self.user_repo.get_by_id.return_value = MagicMock(username="alice")
        for p in (svc_patch, repo_patch, user_patch):
            self.addCleanup(p.stop)

    def _attrs(self):
        return [{"name": "inv", "type": "reference", "ref_kind": "inventory"}]

    def test_ok_for_accessible_inventory(self) -> None:
        self.inv_service.get_inventory.return_value = {"id": 5, "is_active": True}
        validate_reference_inputs(self._attrs(), {"inv": 5}, db=MagicMock(), acting_user_id=1)
        self.inv_service.get_inventory.assert_called_once_with(5, username="alice")

    def test_missing_inventory_raises(self) -> None:
        self.inv_service.get_inventory.return_value = None
        with self.assertRaises(ReferenceValidationError):
            validate_reference_inputs(self._attrs(), {"inv": 9}, db=MagicMock(), acting_user_id=1)

    def test_private_inventory_of_other_user_raises(self) -> None:
        self.inv_service.get_inventory.side_effect = PermissionError("denied")
        with self.assertRaises(ReferenceValidationError):
            validate_reference_inputs(self._attrs(), {"inv": 9}, db=MagicMock(), acting_user_id=1)

    def test_inactive_inventory_raises(self) -> None:
        self.inv_service.get_inventory.return_value = {"id": 5, "is_active": False}
        with self.assertRaises(ReferenceValidationError):
            validate_reference_inputs(self._attrs(), {"inv": 5}, db=MagicMock(), acting_user_id=1)


class CredentialReferenceResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        p = patch("services.credentials.credentials_service.CredentialsService")
        self.cred_service = p.start().return_value
        self.addCleanup(p.stop)

    def _attrs(self):
        return [{"name": "cred", "type": "reference", "ref_kind": "credential"}]

    def _run(self, value="lab-ssh"):
        validate_reference_inputs(
            self._attrs(), {"cred": value}, db=MagicMock(), acting_user_id=1
        )

    def test_ok_for_global_ssh(self) -> None:
        self.cred_service.list_credentials.return_value = [_cred("lab-ssh")]
        self._run()

    def test_unknown_name_raises(self) -> None:
        self.cred_service.list_credentials.return_value = [_cred("other")]
        with self.assertRaises(ReferenceValidationError):
            self._run()

    def test_wrong_type_raises(self) -> None:
        self.cred_service.list_credentials.return_value = [_cred("lab-ssh", cred_type="generic")]
        with self.assertRaises(ReferenceValidationError):
            self._run()

    def test_expired_raises(self) -> None:
        self.cred_service.list_credentials.return_value = [_cred("lab-ssh", status="expired")]
        with self.assertRaises(ReferenceValidationError):
            self._run()

    def test_private_wins_over_global_same_name(self) -> None:
        # global is ssh, private is generic → private is chosen → wrong type → raises
        self.cred_service.list_credentials.return_value = [
            _cred("lab-ssh", cred_type="ssh", visibility="global"),
            _cred("lab-ssh", cred_type="generic", visibility="private"),
        ]
        with self.assertRaises(ReferenceValidationError):
            self._run()

    def test_non_reference_attrs_are_ignored(self) -> None:
        validate_reference_inputs(
            [{"name": "vlan", "type": "number"}],
            {"vlan": 10},
            db=MagicMock(),
            acting_user_id=1,
        )


if __name__ == "__main__":
    unittest.main()

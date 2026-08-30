"""Area 3 — repository / service round-trips on real Postgres.

Things in-memory SQLite can't prove: ``LargeBinary`` columns, JSON columns,
server-default timestamps, unique constraints, RBAC precedence.

Uses the transaction-rollback ``db`` fixture — nothing here persists.
"""

from __future__ import annotations

import uuid

import pytest

from core.models.credentials import Credential
from repositories.inventory_repository import InventoryRepository
from repositories.rbac_repository import RBACRepository
from repositories.settings_repository import SettingsRepository
from repositories.user_repository import UserRepository
from repositories.workflow_repository import WorkflowRepository
from services.auth.auth_service import password_hash
from services.auth.rbac_seed import seed_rbac
from services.auth.rbac_service import RBACService
from services.credentials.credentials_service import CredentialsService
from services.git.repository_service import GitRepositoryService

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("require_postgres")]


def test_credential_password_encrypts_and_round_trips(db) -> None:
    service = CredentialsService(db)
    created = service.create_credential(
        name=f"itest-cred-{uuid.uuid4().hex[:8]}",
        username="netops",
        cred_type="ssh",
        password="s3cret-pw",
        source="general",
        visibility="global",
    )

    row = db.get(Credential, created["id"])
    assert isinstance(row.password_encrypted, (bytes, memoryview))
    assert bytes(row.password_encrypted) != b"s3cret-pw"
    assert row.visibility == "global"
    assert row.owner_user_id is None
    assert row.created_at is not None  # Postgres server_default

    assert service.get_decrypted_password(created["id"]) == "s3cret-pw"


def test_settings_repository_json_value_round_trip(db) -> None:
    repo = SettingsRepository(db)
    payload = {"nested": {"a": 1, "b": [1, 2, 3]}, "flag": True}
    repo.create(key="itest.json.blob", value=payload, description=None)

    fetched = repo.get_by_key("itest.json.blob")
    assert fetched.value == payload

    updated = repo.update(fetched, {"value": {**payload, "flag": False}})
    assert updated.value["flag"] is False

    repo.delete(updated)
    assert repo.get_by_key("itest.json.blob") is None


def test_git_repository_unique_name_constraint(db) -> None:
    service = GitRepositoryService(db)
    name = f"itest-git-{uuid.uuid4().hex[:8]}"
    service.create_repository(
        {"name": name, "category": "device_configs", "url": "http://example.invalid/x.git"}
    )
    with pytest.raises(ValueError):
        service.create_repository(
            {"name": name, "category": "device_configs", "url": "http://example.invalid/y.git"}
        )


def test_workflow_canvas_json_reloads_structurally_equal(db) -> None:
    admin = UserRepository(db).get_by_username("admin")
    nodes = [{"id": "n1", "data": {"kind": "reachable", "pluginConfig": {"ping_count": 2}}}]
    edges = [{"id": "e1", "source": "n1", "target": "n1", "sourceHandle": "success"}]

    wf = WorkflowRepository(db).create(
        name=f"itest-wf-{uuid.uuid4().hex[:8]}",
        creator_id=admin.id,
        description=None,
        folder=None,
        visibility="private",
        canvas_nodes=nodes,
        canvas_edges=edges,
    )
    reloaded, _ = WorkflowRepository(db).get_by_id(wf.id)
    assert reloaded.canvas_nodes == nodes
    assert reloaded.canvas_edges == edges


def test_inventory_get_by_name_active_only(db) -> None:
    repo = InventoryRepository(db)
    inv = repo.create(
        name="itest-inv",
        conditions="[]",
        inventory_type="static",
        device_ids=["a", "b"],
        scope="global",
        created_by="admin",
        is_active=True,
    )
    assert repo.get_by_name("itest-inv", "admin", active_only=True) is not None

    repo.update(inv.id, is_active=False)
    assert repo.get_by_name("itest-inv", "admin", active_only=True) is None
    assert repo.get_by_name("itest-inv", "admin", active_only=False) is not None


def test_seed_rbac_is_idempotent(db) -> None:
    repo = RBACRepository(db)
    seed_rbac(db)
    first = len(repo.list_permissions())
    seed_rbac(db)
    assert len(repo.list_permissions()) == first


def test_rbac_permission_precedence(db) -> None:
    seed_rbac(db)
    rbac_repo = RBACRepository(db)
    rbac = RBACService(db)

    user = UserRepository(db).create_user(
        username=f"itest-rbac-{uuid.uuid4().hex[:8]}",
        password_hash=password_hash.hash("x"),
        is_active=True,
    )
    perm = rbac_repo.get_permission("workflows", "read")

    # default deny
    assert rbac.has_permission(user.id, "workflows", "read") is False

    # role grant
    viewer = rbac_repo.get_role_by_name("viewer")
    rbac_repo.assign_role_to_user(user.id, viewer.id)
    assert rbac.has_permission(user.id, "workflows", "read") is True

    # user override (deny) beats the role grant
    rbac_repo.assign_permission_to_user(user.id, perm.id, granted=False)
    assert rbac.has_permission(user.id, "workflows", "read") is False

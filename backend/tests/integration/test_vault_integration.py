"""OpenBao (Vault) integration — real `OpenBaoService` against a live vault.

Opt-in. Needs a reachable OpenBao (the `docker/openbao` dev container is
enough) with `VAULT_ADDR` + `VAULT_TOKEN` (a root / privileged token, used only
to bootstrap the test mount + policies + AppRoles) in `backend/.env.test`.
Optional `VAULT_KV_MOUNT` (default `manus-itest`) so this never touches a real
`manus` mount.

What it proves that unit tests (all mocked) can't:

* the KV v2 read/write/delete wire shapes are right against a real server;
* the read-only `manus-app` policy actually blocks writes;
* periodic-token `renew-self` works and a revoked token triggers a re-login;
* `CredentialsService` end to end — create a `vault` credential (secret lands
  in OpenBao, DB row holds only the pointer), resolve it through the workflow
  step name path, delete it (secret removed from OpenBao);
* fail-closed: a `vault` credential whose OpenBao is unreachable raises, while a
  `local` credential in the same session still resolves.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import httpx
import pytest

import service_factory
from core.models.credentials import Credential
from services.credentials.credentials_service import CredentialsService
from services.credentials.exceptions import CredentialVaultUnavailableError
from services.vault.client import OpenBaoService
from services.vault.config import VaultConfig
from services.vault.exceptions import (
    VaultError,
    VaultPermissionError,
    VaultSecretNotFoundError,
)
from tests.integration.helpers import env as env_helpers
from tests.integration.helpers.aio import run as _arun
from workflow_steps.common.credential_resolver import resolve_ssh_credential

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("require_openbao", "require_postgres"),
]

_APP_POLICY = """
path "{mount}/data/credentials/*" {{
  capabilities = ["read"]
}}
"""

_MANAGE_POLICY = """
path "{mount}/data/credentials/*" {{
  capabilities = ["create", "read", "update", "delete"]
}}
path "{mount}/delete/credentials/*" {{
  capabilities = ["update"]
}}
path "{mount}/metadata/credentials/*" {{
  capabilities = ["read", "delete"]
}}
path "{mount}/destroy/credentials/*" {{
  capabilities = ["update"]
}}
"""


@dataclass(frozen=True)
class _Bootstrap:
    addr: str
    mount: str
    app_role_id: str
    app_secret_id: str
    manage_role_id: str
    manage_secret_id: str
    root: httpx.Client


def _role_creds(root: httpx.Client, role: str) -> tuple[str, str]:
    role_id = root.get(f"/v1/auth/approle/role/{role}/role-id").json()["data"]["role_id"]
    secret_id = (
        root.post(f"/v1/auth/approle/role/{role}/secret-id").json()["data"]["secret_id"]
    )
    return role_id, secret_id


@pytest.fixture(scope="session")
def vault_bootstrap(require_openbao: None) -> Iterator[_Bootstrap]:
    cfg = env_helpers.openbao()
    mount = cfg.mount
    root = httpx.Client(
        base_url=cfg.addr.rstrip("/"),
        headers={"X-Vault-Token": cfg.token},
        timeout=10.0,
    )
    app_role = f"{mount}-app"
    manage_role = f"{mount}-manage"

    # KV v2 mount (tolerate "already in use")
    resp = root.post(f"/v1/sys/mounts/{mount}", json={"type": "kv", "options": {"version": "2"}})
    if resp.status_code not in (200, 204) and "already in use" not in resp.text:
        resp.raise_for_status()

    root.put(
        f"/v1/sys/policies/acl/{app_role}",
        json={"policy": _APP_POLICY.format(mount=mount)},
    ).raise_for_status()
    root.put(
        f"/v1/sys/policies/acl/{manage_role}",
        json={"policy": _MANAGE_POLICY.format(mount=mount)},
    ).raise_for_status()

    resp = root.post("/v1/sys/auth/approle", json={"type": "approle"})
    if resp.status_code not in (200, 204) and "already in use" not in resp.text:
        resp.raise_for_status()

    for role, policy in ((app_role, app_role), (manage_role, manage_role)):
        root.post(
            f"/v1/auth/approle/role/{role}",
            json={
                "token_policies": policy,
                "token_period": 3600,
                "secret_id_num_uses": 0,
                "secret_id_ttl": 0,
            },
        ).raise_for_status()

    app_rid, app_sid = _role_creds(root, app_role)
    manage_rid, manage_sid = _role_creds(root, manage_role)

    try:
        yield _Bootstrap(
            addr=cfg.addr.rstrip("/"),
            mount=mount,
            app_role_id=app_rid,
            app_secret_id=app_sid,
            manage_role_id=manage_rid,
            manage_secret_id=manage_sid,
            root=root,
        )
    finally:
        for name in (app_role, manage_role):
            try:
                root.delete(f"/v1/sys/policies/acl/{name}")
            except httpx.HTTPError:
                pass
        try:
            root.delete(f"/v1/sys/mounts/{mount}")
        except httpx.HTTPError:
            pass
        root.close()


def _make_service(bs: _Bootstrap, *, role_id: str, secret_id: str, label: str) -> OpenBaoService:
    cfg = VaultConfig(
        addr=bs.addr,
        mount=bs.mount,
        auth_method="approle",
        role_id=role_id,
        secret_id=secret_id,
        token_period_seconds=3600,
        renew_buffer_seconds=600,
        cache_ttl_seconds=30,
        role_label=label,
    )
    svc = OpenBaoService(cfg)
    _arun(svc.startup())
    return svc


@pytest.fixture
def runtime_vault(vault_bootstrap: _Bootstrap) -> Iterator[OpenBaoService]:
    svc = _make_service(
        vault_bootstrap,
        role_id=vault_bootstrap.app_role_id,
        secret_id=vault_bootstrap.app_secret_id,
        label="manus-app",
    )
    prev = service_factory.get_vault_service()
    service_factory.set_vault_service(svc)
    try:
        yield svc
    finally:
        service_factory.set_vault_service(prev)
        _arun(svc.shutdown())


@pytest.fixture
def management_vault(vault_bootstrap: _Bootstrap) -> Iterator[OpenBaoService]:
    svc = _make_service(
        vault_bootstrap,
        role_id=vault_bootstrap.manage_role_id,
        secret_id=vault_bootstrap.manage_secret_id,
        label="manus-manage",
    )
    prev = service_factory.get_vault_management_service()
    service_factory.set_vault_management_service(svc)
    try:
        yield svc
    finally:
        service_factory.set_vault_management_service(prev)
        _arun(svc.shutdown())


def _p(prefix: str) -> str:
    return f"credentials/itest-{prefix}-{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------- #
# Wire-level
# --------------------------------------------------------------------------- #
def test_management_write_then_runtime_read(runtime_vault, management_vault) -> None:
    path = _p("rw")
    management_vault.write_kv(path, {"token": "abc123"})
    try:
        assert runtime_vault.read_kv(path) == {"token": "abc123"}
    finally:
        management_vault.delete_kv(path)


def test_runtime_role_cannot_write(runtime_vault) -> None:
    with pytest.raises(VaultPermissionError):
        runtime_vault.write_kv(_p("ro"), {"token": "nope"})


def test_read_missing_path_raises_not_found(runtime_vault) -> None:
    with pytest.raises(VaultSecretNotFoundError):
        runtime_vault.read_kv(_p("missing"))


def test_delete_removes_the_secret(runtime_vault, management_vault, vault_bootstrap) -> None:
    path = _p("del")
    management_vault.write_kv(path, {"password": "x"})
    management_vault.delete_kv(path)
    with pytest.raises(VaultSecretNotFoundError):
        runtime_vault.read_kv(path)
    # V3: delete_kv destroys every KV v2 version via the metadata endpoint, not
    # just a soft-delete of the latest one.
    metadata_resp = vault_bootstrap.root.get(
        f"/v1/{vault_bootstrap.mount}/metadata/{path}"
    )
    assert metadata_resp.status_code == 404


def test_update_destroys_the_superseded_version(
    runtime_vault, management_vault, vault_bootstrap
) -> None:
    path = _p("rotate")
    management_vault.write_kv(path, {"password": "v1"})
    try:
        new_version = management_vault.write_kv(path, {"password": "v2"})
        assert new_version == 2
        management_vault.destroy_kv_versions(path, [1])

        data_resp = vault_bootstrap.root.get(
            f"/v1/{vault_bootstrap.mount}/data/{path}", params={"version": 1}
        )
        assert data_resp.json()["data"]["metadata"]["destroyed"] is True
    finally:
        management_vault.delete_kv(path)


# --------------------------------------------------------------------------- #
# Token lifecycle
# --------------------------------------------------------------------------- #
def test_token_renew_self(runtime_vault, management_vault) -> None:
    path = _p("renew")
    management_vault.write_kv(path, {"token": "keeps-working"})
    try:
        runtime_vault._tokens.renew(runtime_vault._client)
        assert runtime_vault._tokens.current()
        assert runtime_vault.read_kv(path) == {"token": "keeps-working"}
    finally:
        management_vault.delete_kv(path)


def test_revoked_token_triggers_relogin(
    runtime_vault, management_vault, vault_bootstrap
) -> None:
    path = _p("revoke")
    management_vault.write_kv(path, {"token": "after-relogin"})
    try:
        old_token = runtime_vault._tokens.current()
        vault_bootstrap.root.post(
            "/v1/auth/token/revoke", json={"token": old_token}
        ).raise_for_status()

        # First call: the revoked token is rejected (invalidated internally).
        with pytest.raises(VaultError):
            runtime_vault.read_kv(path)
        # Second call: transparent re-login with a fresh token.
        assert runtime_vault.read_kv(path) == {"token": "after-relogin"}
        assert runtime_vault._tokens.current() != old_token
    finally:
        management_vault.delete_kv(path)


# --------------------------------------------------------------------------- #
# CredentialsService end to end
# --------------------------------------------------------------------------- #
def test_vault_credential_end_to_end(runtime_vault, management_vault, db) -> None:
    name = f"itest-vault-{uuid.uuid4().hex[:8]}"
    service = service_factory.build_credentials_service(db, with_management=True)

    created = service.create_credential(
        name=name,
        username="netops",
        cred_type="ssh",
        password="s3cret-pw",
        source="general",
        visibility="global",
        storage_backend="vault",
    )
    vault_path = None
    try:
        row = db.get(Credential, created["id"])
        vault_path = row.vault_path
        assert row.storage_backend == "vault"
        assert row.vault_path == f"credentials/{name}-{row.id}"
        assert row.password_encrypted is None
        assert row.vault_secret_fields == "password"

        # secret really is in OpenBao, not the DB
        assert runtime_vault.read_kv(row.vault_path) == {"password": "s3cret-pw"}

        # resolves through CredentialsService …
        assert service.get_decrypted_password(created["id"]) == "s3cret-pw"

        # … and through the workflow-step name resolver (uses the runtime
        # singleton registered by the fixture)
        username, password = resolve_ssh_credential(db, name, acting_user_id=None)
        assert (username, password) == ("netops", "s3cret-pw")

        # delete drops the OpenBao secret too (clear the runtime reader's own
        # short-TTL cache first — it is per-instance and delete went through the
        # management client)
        service.delete_credential(created["id"])
        runtime_vault._cache.clear()
        with pytest.raises(VaultSecretNotFoundError):
            runtime_vault.read_kv(row.vault_path)
        vault_path = None
    finally:
        if vault_path is not None:
            try:
                management_vault.delete_kv(vault_path)
            except VaultError:
                pass


def test_fail_closed_when_openbao_unreachable(management_vault, db) -> None:
    name_vault = f"itest-fc-vault-{uuid.uuid4().hex[:8]}"
    name_local = f"itest-fc-local-{uuid.uuid4().hex[:8]}"
    wired = service_factory.build_credentials_service(db, with_management=True)
    created = wired.create_credential(
        name=name_vault,
        username="netops",
        cred_type="ssh",
        password="vault-pw",
        source="general",
        visibility="global",
        storage_backend="vault",
    )
    vault_path = db.get(Credential, created["id"]).vault_path
    try:
        dead = OpenBaoService(
            VaultConfig(
                addr="http://127.0.0.1:1",
                mount="manus-itest",
                auth_method="token",
                token="unused",
            )
        )
        service = CredentialsService(db, vault_reader=dead)

        with pytest.raises(CredentialVaultUnavailableError):
            service.get_decrypted_password(created["id"])

        # a local credential in the same session is unaffected
        local = service.create_credential(
            name=name_local,
            username="admin",
            cred_type="ssh",
            password="local-pw",
            source="general",
            visibility="global",
            storage_backend="local",
        )
        assert service.get_decrypted_password(local["id"]) == "local-pw"
    finally:
        try:
            management_vault.delete_kv(vault_path)
        except VaultError:
            pass

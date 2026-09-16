"""TestClient tests for the encrypt/decrypt-attribute editor Test APIs."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from routers import workflow_crypto_attribute
from routers.workflow_crypto_attribute import router as crypto_router
from services.auth.rbac_service import RBACService
from workflow_steps.common.credential_resolver import CredentialReferenceNotFoundError


def _make_user(user_id: int = 1) -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = user_id
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(crypto_router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = lambda: _make_user(1)
    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def test_encrypt_then_decrypt_round_trip(client: TestClient) -> None:
    enc = client.post(
        "/api/workflow-steps/encrypt-attribute/test",
        json={"plaintext": "cisco123", "shared_secret": "vault-key"},
    )
    assert enc.status_code == 200, enc.text
    body = enc.json()
    assert body["algorithm"] == "aes-256-gcm"
    token = body["ciphertext"]

    dec = client.post(
        "/api/workflow-steps/decrypt-attribute/test",
        json={"ciphertext": token, "shared_secret": "vault-key"},
    )
    assert dec.status_code == 200, dec.text
    assert dec.json() == {"plaintext": "cisco123", "algorithm": "aes-256-gcm"}


def test_decrypt_wrong_secret_is_400(client: TestClient) -> None:
    token = client.post(
        "/api/workflow-steps/encrypt-attribute/test",
        json={"plaintext": "x", "shared_secret": "right"},
    ).json()["ciphertext"]

    resp = client.post(
        "/api/workflow-steps/decrypt-attribute/test",
        json={"ciphertext": token, "shared_secret": "wrong"},
    )
    assert resp.status_code == 400


def test_encrypt_unknown_algorithm_is_400(client: TestClient) -> None:
    resp = client.post(
        "/api/workflow-steps/encrypt-attribute/test",
        json={"plaintext": "x", "shared_secret": "k", "algorithm": "rot13"},
    )
    assert resp.status_code == 400


def test_decrypt_malformed_token_is_400(client: TestClient) -> None:
    resp = client.post(
        "/api/workflow-steps/decrypt-attribute/test",
        json={"ciphertext": "not-a-real-token", "shared_secret": "k"},
    )
    assert resp.status_code == 400


def test_both_secret_sources_is_422(client: TestClient) -> None:
    resp = client.post(
        "/api/workflow-steps/encrypt-attribute/test",
        json={"plaintext": "x", "shared_secret": "k", "credential_reference": "vault-cred"},
    )
    assert resp.status_code == 422


def test_neither_secret_source_is_422(client: TestClient) -> None:
    resp = client.post(
        "/api/workflow-steps/encrypt-attribute/test",
        json={"plaintext": "x"},
    )
    assert resp.status_code == 422


def test_encrypt_with_credential_reference_resolves_from_vault(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        workflow_crypto_attribute,
        "resolve_shared_secret_credential",
        lambda db, name, *, acting_user_id: ("aes-256-gcm", "vault-key"),
    )

    enc = client.post(
        "/api/workflow-steps/encrypt-attribute/test",
        json={"plaintext": "cisco123", "credential_reference": "tacacs-vault"},
    )
    assert enc.status_code == 200, enc.text
    token = enc.json()["ciphertext"]

    dec = client.post(
        "/api/workflow-steps/decrypt-attribute/test",
        json={"ciphertext": token, "credential_reference": "tacacs-vault"},
    )
    assert dec.status_code == 200, dec.text
    assert dec.json() == {"plaintext": "cisco123", "algorithm": "aes-256-gcm"}


def test_unknown_credential_reference_is_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(db, name, *, acting_user_id):
        raise CredentialReferenceNotFoundError(f"credential {name!r} not found")

    monkeypatch.setattr(
        workflow_crypto_attribute, "resolve_shared_secret_credential", _raise
    )

    resp = client.post(
        "/api/workflow-steps/encrypt-attribute/test",
        json={"plaintext": "x", "credential_reference": "missing"},
    )
    assert resp.status_code == 400

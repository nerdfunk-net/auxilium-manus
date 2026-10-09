"""Request bodies that declare an oversize Content-Length get a 413 (S15)."""

from __future__ import annotations

from fastapi.testclient import TestClient

import main
from core.config import settings


def test_declared_oversize_body_413(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_request_body_bytes", 100)
    with TestClient(main.app) as client:
        response = client.post(
            "/definitely-not-a-route", content=b"x" * 101, headers={"content-length": "101"}
        )
    assert response.status_code == 413
    assert response.json() == {"detail": "Request body too large"}


def test_body_at_the_limit_is_not_rejected(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_request_body_bytes", 100)
    with TestClient(main.app) as client:
        response = client.post("/definitely-not-a-route", content=b"x" * 100)
    assert response.status_code != 413


def test_limit_zero_disables(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_request_body_bytes", 0)
    with TestClient(main.app) as client:
        response = client.post("/definitely-not-a-route", content=b"x" * 5000)
    assert response.status_code != 413

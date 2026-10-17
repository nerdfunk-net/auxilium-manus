"""/reports: permission gate, validation errors, rate limiting, end to end on SQLite."""

from __future__ import annotations

import pytest
from _auth_helpers import make_auth_db, make_user, token_payload
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.base import Base
from core.models.report_data_records import ReportDataRecord
from core.models.report_datasets import ReportDataset
from routers.reports import get_report_query_service, router
from services.auth.rbac_service import RBACService
from services.reports.report_query_service import ReportQueryService


@pytest.fixture
def allowed(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    state = {"value": True}
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: state["value"])
    return state


@pytest.fixture
def client(allowed: dict[str, bool]) -> TestClient:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[ReportDataRecord.__table__, ReportDataset.__table__])
    session = sessionmaker(bind=engine)()
    session.add(ReportDataset(dataset="inventory", mode="device", field_names=["location"]))
    session.add(
        ReportDataRecord(
            device_name="sw1", dataset="inventory", data={"location": "dc1"}, collection_id="c1"
        )
    )
    session.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: make_user(1)
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    app.dependency_overrides[get_report_query_service] = lambda: ReportQueryService(session)
    return TestClient(app)


def test_sources_catalog_and_query(client: TestClient) -> None:
    assert client.get("/api/reports/sources").json() == [
        {"id": "report_data", "label": "Report database"}
    ]

    catalog = client.get("/api/reports/sources/report_data/catalog").json()
    assert catalog[0]["name"] == "inventory"
    assert catalog[0]["fields"][0]["type"] == "string"

    response = client.post(
        "/api/reports/sources/report_data/query",
        json={"dataset": "inventory", "group_by": ["location"], "metrics": [{"op": "count"}]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["rows"] == [["dc1", 1]]
    assert [c["key"] for c in response.json()["columns"]] == ["location", "count"]


def test_requires_reports_read(client: TestClient, allowed: dict[str, bool]) -> None:
    allowed["value"] = False
    assert client.get("/api/reports/sources").status_code == 403
    assert client.get("/api/reports/sources/report_data/catalog").status_code == 403
    assert (
        client.post("/api/reports/sources/report_data/query", json={"dataset": "x"}).status_code
        == 403
    )


def test_invalid_query_is_422_with_a_message(client: TestClient) -> None:
    response = client.post(
        "/api/reports/sources/report_data/query",
        json={"dataset": "inventory", "select": ["nope"]},
    )
    assert response.status_code == 422
    assert "unknown field" in response.json()["detail"]


def test_malformed_query_body_is_422(client: TestClient) -> None:
    for body in ({"dataset": "x", "extra": 1}, {"dataset": "x", "limit": 0}, {}):
        response = client.post("/api/reports/sources/report_data/query", json=body)
        assert response.status_code == 422, body


def test_unknown_source_is_404(client: TestClient) -> None:
    assert client.get("/api/reports/sources/nope/catalog").status_code == 404
    assert client.post("/api/reports/sources/nope/query", json={"dataset": "x"}).status_code == 404


def test_query_route_is_rate_limited() -> None:
    by_path = {route.path: route for route in router.routes if getattr(route, "methods", None)}
    names = [
        d.call.__name__
        for d in by_path["/reports/sources/{source_id}/query"].dependant.dependencies
    ]  # type: ignore[attr-defined]
    assert "rate_limited_reports-query" in names

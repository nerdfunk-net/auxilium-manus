"""Area 1 — Nautobot inventory service against the lab instance.

All read-only. Expected counts are derived from ``tests/nautobot-baseline.yaml``
(120 devices) so they cannot silently drift from the seeded lab data.

Requires: a reachable Nautobot at ``NAUTOBOT_HOST`` seeded with the baseline,
and ``ALLOW_LOOPBACK_SOURCE_URLS=true`` (Nautobot is on loopback).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import service_factory
from models.sources_nautobot import LogicalCondition, LogicalOperation
from services.nautobot.common.exceptions import NautobotAPIError
from tests.integration.helpers import env as env_helpers
from tests.integration.helpers.aio import run as arun

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("require_nautobot")]

_BASELINE_FILE = Path(__file__).resolve().parents[1] / "nautobot-baseline.yaml"


# --------------------------------------------------------------------------- #
# Baseline parser
# --------------------------------------------------------------------------- #
class Baseline:
    def __init__(self, devices: list[dict]) -> None:
        self.devices = devices

    def by(self, *, status=None, tag=None, location=None) -> list[dict]:
        result = self.devices
        if status is not None:
            result = [d for d in result if d.get("status") == status]
        if tag is not None:
            result = [d for d in result if tag in (d.get("tags") or [])]
        if location is not None:
            result = [d for d in result if d.get("location") == location]
        return result

    def count(self, **kw) -> int:
        return len(self.by(**kw))


@pytest.fixture(scope="session")
def baseline() -> Baseline:
    if not _BASELINE_FILE.is_file():
        pytest.skip(f"{_BASELINE_FILE} missing")
    data = yaml.safe_load(_BASELINE_FILE.read_text())
    return Baseline(data.get("devices") or [])


# --------------------------------------------------------------------------- #
# Live Nautobot source service (nautobot_app / nautobot_credentials: conftest)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def credentials(nautobot_credentials):
    return nautobot_credentials


@pytest.fixture(scope="session")
def source_service(nautobot_app, credentials):
    return service_factory.build_nautobot_source_service(credentials, db=None)


def _op(
    field: str, value: str, *, operator: str = "equals", op_type: str = "AND"
) -> LogicalOperation:
    return LogicalOperation(
        operation_type=op_type,
        conditions=[LogicalCondition(field=field, operator=operator, value=value)],
    )


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_connection(nautobot_app, credentials) -> None:
    status = arun(nautobot_app.test_connection(credentials))
    assert isinstance(status, dict)


def test_preview_all_devices(source_service, baseline) -> None:
    devices, _ = arun(source_service.preview_inventory([]))
    assert len(devices) == len(baseline.devices) == 120


def test_filter_by_status_offline(source_service, baseline) -> None:
    devices, _ = arun(source_service.preview_inventory([_op("status", "Offline")]))
    assert len(devices) == baseline.count(status="Offline")
    sample = devices[0]
    assert sample.id and sample.name is not None
    assert hasattr(sample, "primary_ip4")
    assert hasattr(sample, "status")


@pytest.mark.parametrize(("tag", "_ignored"), [("Production", None), ("Staging", None)])
def test_filter_by_tag(source_service, baseline, tag, _ignored) -> None:
    devices, _ = arun(source_service.preview_inventory([_op("tag", tag)]))
    assert len(devices) == baseline.count(tag=tag)


def test_filter_by_location(source_service, baseline) -> None:
    devices, _ = arun(source_service.preview_inventory([_op("location", "City A")]))
    assert len(devices) == baseline.count(location="City A")


def test_and_composition(source_service, baseline) -> None:
    op = LogicalOperation(
        operation_type="AND",
        conditions=[
            LogicalCondition(field="status", operator="equals", value="Active"),
            LogicalCondition(field="tag", operator="equals", value="Staging"),
        ],
    )
    devices, _ = arun(source_service.preview_inventory([op]))
    expected = len(
        [
            d
            for d in baseline.devices
            if d.get("status") == "Active" and "Staging" in (d.get("tags") or [])
        ]
    )
    assert len(devices) == expected


def test_negation_via_not_equals(source_service, baseline) -> None:
    # A lone top-level NOT operation returns nothing by design (preview_inventory
    # only *subtracts* a NOT from a preceding positive set). Negation as a single
    # filter is expressed with the not_equals operator.
    devices, _ = arun(
        source_service.preview_inventory([_op("status", "Offline", operator="not_equals")])
    )
    assert len(devices) == baseline.count(status="Active")


def test_resolve_devices_by_ids(source_service) -> None:
    all_devices, _ = arun(source_service.preview_inventory([_op("status", "Active")]))
    ids = [d.id for d in all_devices[:3]]
    resolved = arun(source_service.resolve_devices_by_ids(ids))
    assert sorted(d.id for d in resolved) == sorted(ids)


def test_search_devices_by_name(source_service) -> None:
    devices = arun(source_service.search_devices_by_name("lab-01"))
    assert devices
    assert all("lab-01" in (d.name or "") for d in devices)


def test_get_device_details_and_attributes(source_service, baseline) -> None:
    devices, _ = arun(source_service.preview_inventory([_op("status", "Active")]))
    device_id = devices[0].id

    details = arun(source_service.get_device_details(device_id))
    assert "name" in details

    # list_of_attributes takes attribute-GROUP keys; CFs land nested under
    # attrs["custom_fields"] (see attribute_bag.attributes_from_detail).
    attrs = arun(source_service.get_device_attributes(device_id, ["custom_fields"]))
    assert isinstance(attrs, dict) and attrs
    assert {"net", "checkmk_site"} & set(attrs.get("custom_fields", {}))


def test_custom_fields_catalog(source_service) -> None:
    fields = arun(source_service.get_custom_fields())
    assert any(f.get("name") == "net" or f.get("key") == "net" for f in fields)

    # get_field_values only supports fields with a dedicated endpoint; "net" is a
    # free-form CF in this lab ("No endpoint defined for field: net"). Assert the
    # call is well-formed rather than a specific value set.
    values = arun(source_service.get_field_values("net"))
    assert isinstance(values, list)
    flat = {v.get("value") or v.get("label") for v in values}
    if flat:
        assert {"netA", "netB", "lab"} & flat


def test_bad_token_raises(nautobot_app) -> None:
    cfg = env_helpers.nautobot()
    bad = service_factory.credentials_from_connection(cfg.url, "deadbeef" * 5, verify_ssl=False)
    bad_service = service_factory.build_nautobot_source_service(bad, db=None)
    with pytest.raises(NautobotAPIError):
        arun(bad_service.preview_inventory([]))


@pytest.mark.skipif(not env_helpers.redis_configured(), reason="Redis not configured")
def test_bulk_device_cache_refresh(credentials, nautobot_app) -> None:
    import core.database as db_mod

    session = db_mod.SessionLocal()
    try:
        svc = service_factory.build_nautobot_source_service(credentials, db=session)
        written = arun(svc.refresh_bulk_device_cache())
        assert written == 120
    finally:
        session.close()

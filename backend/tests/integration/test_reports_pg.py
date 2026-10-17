"""Area 3 — the Reports query engine on real PostgreSQL (JSONB).

What in-memory SQLite can't prove: ``->>`` extraction and casts on JSONB, boolean and mixed
values, ``date_trunc`` buckets, and the cost of the latest-collection scan on a large table.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert

import core.database as db_mod
from core.models.report_data_records import ReportDataRecord
from models.reports import DatasetInfo, FieldInfo, ReportQuery
from services.report_data.report_data_service import ReportDataService
from services.reports import query_compiler
from services.reports.errors import ReportQueryError
from services.reports.query_compiler import execute_query
from services.reports.sources.report_data_source import ReportDataSource

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("require_postgres", "clean_tables"),
]

NOW = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)


@pytest.fixture
def session():
    s = db_mod.SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def source(session):
    return ReportDataSource(session)


def _device(session, device: str, data: dict, *, at: datetime = NOW) -> None:
    """Write through the service (catalog included), then move the rows to *at*."""
    ReportDataService(session).record_device_data(
        device_name=device, dataset="inventory", data=data
    )
    session.query(ReportDataRecord).filter(
        ReportDataRecord.device_name == device, ReportDataRecord.created_at > at
    ).update({"created_at": at})
    session.commit()


def _seed(session) -> None:
    _device(session, "sw1", {"serial": "A1", "location": "dc1", "ports": 48, "stacked": True})
    _device(session, "sw2", {"serial": "B2", "location": "dc1", "ports": 24, "stacked": False})
    _device(session, "sw3", {"serial": "C3", "location": "dc2", "ports": 48, "stacked": None})
    _device(session, "sw4", {"serial": None, "location": "dc2", "ports": None, "stacked": None})


def _run(source, **query):
    return source.run(ReportQuery.model_validate({"dataset": "inventory", **query}))


def test_catalog_types_on_jsonb(session, source) -> None:
    _seed(session)

    (info,) = source.describe()

    types = {f.name: f.type for f in info.fields}
    assert types == {
        "serial": "string",
        "location": "string",
        "ports": "number",
        "stacked": "boolean",
    }


def test_filters_on_every_type(session, source) -> None:
    _seed(session)

    def devices(*filters):
        return [r[0] for r in _run(source, select=["device_name"], filters=list(filters)).rows]

    assert devices({"field": "location", "op": "eq", "value": "dc1"}) == ["sw1", "sw2"]
    assert devices({"field": "serial", "op": "ne", "value": "A1"}) == ["sw2", "sw3", "sw4"]
    assert devices({"field": "ports", "op": "gt", "value": 24}) == ["sw1", "sw3"]
    assert devices({"field": "ports", "op": "eq", "value": 48}) == ["sw1", "sw3"]
    assert devices({"field": "stacked", "op": "eq", "value": True}) == ["sw1"]
    assert devices({"field": "stacked", "op": "eq", "value": False}) == ["sw2"]
    assert devices({"field": "serial", "op": "is_null"}) == ["sw4"]
    assert devices({"field": "ports", "op": "not_null"}) == ["sw1", "sw2", "sw3"]
    assert devices({"field": "device_name", "op": "in", "value": ["sw2", "sw4"]}) == ["sw2", "sw4"]
    assert devices({"field": "serial", "op": "contains", "value": "b"}) == ["sw2"]


def test_contains_escapes_like_wildcards(session, source) -> None:
    _device(session, "sw1", {"serial": "50%_off"})
    _device(session, "sw2", {"serial": "500 total"})

    rows = _run(
        source,
        select=["device_name"],
        filters=[{"field": "serial", "op": "contains", "value": "%_"}],
    ).rows

    assert rows == [["sw1"]]


def test_mixed_field_distinguishes_number_string_and_boolean(session, source) -> None:
    _device(session, "sw1", {"misc": 10})
    _device(session, "sw2", {"misc": "10"})
    _device(session, "sw3", {"misc": True})

    def devices(value):
        flt = [{"field": "misc", "op": "eq", "value": value}]
        return [r[0] for r in _run(source, select=["device_name"], filters=flt).rows]

    (info,) = source.describe()
    assert info.fields[0].type == "mixed"
    assert devices(10) == ["sw1"]
    assert devices("10") == ["sw2"]
    assert devices(True) == ["sw3"]


def test_aggregates(session, source) -> None:
    _seed(session)

    result = _run(
        source,
        metrics=[
            {"op": "count"},
            {"op": "sum", "field": "ports"},
            {"op": "avg", "field": "ports"},
            {"op": "min", "field": "ports"},
            {"op": "max", "field": "ports"},
            {"op": "count_distinct", "field": "location"},
            {"op": "count_missing", "field": "serial"},
        ],
    )

    assert result.rows == [[4, 120.0, 40.0, 24.0, 48.0, 2, 1]]


def test_group_by_and_order(session, source) -> None:
    _seed(session)

    result = _run(
        source,
        group_by=["location"],
        metrics=[
            {"op": "count", "alias": "devices"},
            {"op": "sum", "field": "ports", "alias": "ports"},
        ],
        order_by=[{"key": "location", "direction": "desc"}],
    )

    assert result.rows == [["dc2", 2, 48.0], ["dc1", 2, 72.0]]


def test_latest_scope_uses_only_the_newest_collection(session, source) -> None:
    _device(session, "sw1", {"serial": "OLD"}, at=NOW - timedelta(days=2))
    _device(session, "sw1", {"serial": "NEW"})

    assert _run(source, select=["serial"]).rows == [["NEW"]]
    history = _run(source, select=["serial"], scope={"kind": "history"}).rows
    assert sorted(r[0] for r in history) == ["NEW", "OLD"]


def test_day_and_week_buckets(session, source) -> None:
    _device(session, "a", {"ports": 10}, at=datetime(2026, 1, 5, 9, tzinfo=UTC))  # Monday
    _device(session, "b", {"ports": 20}, at=datetime(2026, 1, 5, 17, tzinfo=UTC))
    _device(session, "c", {"ports": 30}, at=datetime(2026, 1, 11, 8, tzinfo=UTC))  # Sunday
    _device(session, "d", {"ports": 40}, at=datetime(2026, 1, 12, 8, tzinfo=UTC))  # next Monday

    daily = _run(
        source,
        scope={"kind": "history", "bucket": "day"},
        group_by=["time_bucket"],
        metrics=[{"op": "avg", "field": "ports", "alias": "avg_ports"}],
    )
    weekly = _run(
        source,
        scope={"kind": "history", "bucket": "week"},
        group_by=["time_bucket"],
        metrics=[{"op": "count"}],
    )

    assert [row[1] for row in daily.rows] == [15.0, 30.0, 40.0]
    assert [row[1] for row in weekly.rows] == [3, 1]
    assert isinstance(daily.rows[0][0], datetime)


def test_items_dataset_count_of_shutdown_interfaces(session, source) -> None:
    service = ReportDataService(session)
    service.record_device_items(
        device_name="sw1",
        dataset="ifaces",
        items=[{"name": "Gi1", "status": "up"}, {"name": "Gi2", "status": "disabled"}],
    )
    service.record_device_items(
        device_name="sw2", dataset="ifaces", items=[], field_names=["name", "status"]
    )
    service.record_device_items(
        device_name="sw3", dataset="ifaces", items=[{"name": "Gi1", "status": "disabled"}]
    )

    result = source.run(
        ReportQuery.model_validate(
            {
                "dataset": "ifaces",
                "filters": [{"field": "status", "op": "eq", "value": "disabled"}],
                "group_by": ["device_name"],
                "metrics": [{"op": "count", "alias": "shutdown"}],
            }
        )
    )

    assert result.rows == [["sw1", 1], ["sw3", 1]]


def test_catalog_tracks_grain_and_fields(session, source) -> None:
    service = ReportDataService(session)
    service.record_device_items(device_name="sw1", dataset="ifaces", items=[{"name": "Gi1"}])
    _device(session, "sw1", {"serial": "A"})

    modes = {info.name: info.mode for info in source.describe()}

    assert modes == {"ifaces": "items", "inventory": "device"}


def test_latest_scan_on_a_large_table_is_fast(session, source) -> None:
    rows = [
        {
            "device_name": f"sw{device}",
            "dataset": "big",
            "data": {"location": f"dc{device % 10}", "ports": device % 48},
            "collection_id": f"c-{device}-{collection}",
            "created_at": NOW - timedelta(minutes=collection),
        }
        for device in range(500)
        for collection in range(100)
    ]
    session.execute(insert(ReportDataRecord), rows)
    session.commit()

    started = time.perf_counter()
    result = (
        source.run(
            ReportQuery.model_validate(
                {"dataset": "big", "group_by": ["location"], "metrics": [{"op": "count"}]}
            )
        )
        if _catalog(session, "big")
        else None
    )
    elapsed = time.perf_counter() - started

    assert result is not None
    assert sum(row[1] for row in result.rows) == 500
    assert elapsed < 5.0, f"latest-scope aggregate took {elapsed:.2f}s on 50,000 rows"


def _catalog(session, dataset: str) -> bool:
    from repositories.report_datasets_repository import ReportDatasetRepository

    ReportDatasetRepository(session).upsert(
        dataset=dataset, mode="device", field_names=["location", "ports"]
    )
    return True


def _typed_dataset() -> DatasetInfo:
    fields = [
        FieldInfo(name="ports", type="number", null_share=0.0, sample_values=[]),
        FieldInfo(name="stacked", type="boolean", null_share=0.0, sample_values=[]),
    ]
    return DatasetInfo(name="inventory", mode="device", fields=fields)


def test_a_stray_value_of_another_type_does_not_break_numeric_or_boolean_queries(
    session,
) -> None:
    # The catalog types come from a sample; older/other rows may hold something else.
    _device(session, "sw1", {"ports": 48, "stacked": True})
    _device(session, "sw2", {"ports": "N/A", "stacked": "yes"})
    _device(session, "sw3", {"ports": 24, "stacked": False})
    dataset = _typed_dataset()

    def run(**query):
        return execute_query(
            session, ReportQuery.model_validate({"dataset": "inventory", **query}), dataset
        )

    totals = run(
        metrics=[
            {"op": "sum", "field": "ports"},
            {"op": "avg", "field": "ports"},
            {"op": "count_missing", "field": "ports"},
        ]
    )
    assert totals.rows == [[72.0, 36.0, 1]]
    big = run(select=["device_name"], filters=[{"field": "ports", "op": "gt", "value": 30}])
    assert big.rows == [["sw1"]]
    stacked = run(select=["device_name"], filters=[{"field": "stacked", "op": "eq", "value": True}])
    assert stacked.rows == [["sw1"]]


def test_an_over_long_query_is_cancelled_with_a_clear_error(session, monkeypatch) -> None:
    rows = [
        {
            "device_name": f"sw{device}",
            "dataset": "big",
            "data": {"location": f"dc{device % 10}"},
            "collection_id": f"c-{device}-{collection}",
            "created_at": NOW - timedelta(minutes=collection),
        }
        for device in range(300)
        for collection in range(100)
    ]
    session.execute(insert(ReportDataRecord), rows)
    session.commit()
    monkeypatch.setattr(query_compiler, "STATEMENT_TIMEOUT_MS", 1)
    dataset = DatasetInfo(
        name="big",
        mode="device",
        fields=[FieldInfo(name="location", type="string", null_share=0.0, sample_values=[])],
    )

    with pytest.raises(ReportQueryError, match="too long"):
        execute_query(
            session,
            ReportQuery.model_validate(
                {
                    "dataset": "big",
                    "scope": {"kind": "history"},
                    "group_by": ["location"],
                    "metrics": [{"op": "count_distinct", "field": "device_name"}],
                }
            ),
            dataset,
        )


def test_count_items_shows_a_device_with_no_items_as_zero(session, source) -> None:
    service = ReportDataService(session)
    service.record_device_items(device_name="sw1", dataset="ifaces", items=[{"n": "a"}, {"n": "b"}])
    service.record_device_items(device_name="sw2", dataset="ifaces", items=[])

    result = source.run(
        ReportQuery.model_validate(
            {
                "dataset": "ifaces",
                "group_by": ["device_name"],
                "metrics": [{"op": "count_items", "alias": "items"}],
            }
        )
    )
    totals = source.run(
        ReportQuery.model_validate(
            {"dataset": "ifaces", "metrics": [{"op": "count_devices", "alias": "devices"}]}
        )
    )

    assert result.rows == [["sw1", 2], ["sw2", 0]]
    assert totals.rows == [[2]]


def test_purge_keeps_the_newest_collection_per_device_and_dataset(session) -> None:
    service = ReportDataService(session)
    old = NOW - timedelta(days=400)
    for index in range(3):
        service.record_device_data(device_name="sw1", dataset="inventory", data={"v": index})
    service.record_device_data(device_name="sw2", dataset="inventory", data={"v": 9})
    session.query(ReportDataRecord).filter(ReportDataRecord.device_name == "sw2").update(
        {"created_at": old}
    )
    oldest = session.query(ReportDataRecord).filter(ReportDataRecord.device_name == "sw1")
    ids = [row.id for row in oldest.order_by(ReportDataRecord.id)]
    session.query(ReportDataRecord).filter(ReportDataRecord.id.in_(ids[:2])).update(
        {"created_at": old}, synchronize_session=False
    )
    session.commit()

    deleted = service.purge_older_than_days(365, batch_size=1)

    assert deleted == 2
    kept = {(r.device_name, r.data["v"]) for r in session.query(ReportDataRecord)}
    assert kept == {("sw1", 2), ("sw2", 9)}

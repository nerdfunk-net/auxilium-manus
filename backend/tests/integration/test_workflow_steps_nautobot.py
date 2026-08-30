"""Area 4 — Nautobot-backed workflow steps (plan §7.2).

Direct executor calls. The ``run`` is attached to a live session that also
holds the seeded ``sources.nautobot.itest`` setting, so the executors'
``object_session(run)`` → ``resolve_nautobot_credentials`` path is exercised
end to end.
"""

from __future__ import annotations

import pytest

import core.database as db_mod
from models.workflow_context import WorkflowContext
from services.artifacts import InMemoryArtifactService
from tests.integration.helpers.aio import run as arun
from tests.integration.helpers.workflows import build_linear_workflow, make_run, node
from workflow_steps.get_nautobot_attributes.executor import execute as get_nautobot_attributes
from workflow_steps.get_nautobot_devices.executor import execute as get_nautobot_devices

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("require_nautobot", "require_postgres", "clean_tables"),
]


@pytest.fixture
def session():
    s = db_mod.SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def run(session, admin_user, nautobot_source, nautobot_app):
    wf = build_linear_workflow(
        session,
        creator_id=admin_user.id,
        nodes=[node("n1", "get-nautobot-devices", {})],
    )
    return make_run(session, workflow=wf, triggered_by_id=admin_user.id)


def _ctx(run) -> WorkflowContext:
    return WorkflowContext(run_id=run.uuid, workflow_id=str(run.workflow_id))


def _filter(field: str, value: str, *, operator: str = "equals") -> dict:
    return {
        "logic": "AND",
        "negate": False,
        "id": "root",
        "items": [{"field": field, "operator": operator, "value": value}],
    }


def _call(executor, run, config, ctx=None, node_id="n1"):
    async def _body():
        return await executor(
            config=config,
            context=ctx or _ctx(run),
            run=run,
            artifact_service=InMemoryArtifactService(),
            node_id=node_id,
            device_sessions=None,
        )

    return arun(_body())


# --------------------------------------------------------------------------- #
def test_get_nautobot_devices_filter(run) -> None:
    outcomes = _call(
        get_nautobot_devices,
        run,
        {
            "nautobot_source_id": "itest",
            "inventory_type": "filter",
            "device_filter": _filter("status", "Offline"),
        },
    )
    ctx = next(o for o in outcomes if o.name == "success").context
    assert len(ctx.devices) == 54
    assert ctx.metadata["n1.total"] == 54
    assert all(d.source_id == "itest" for d in ctx.devices.values())


def test_get_nautobot_devices_static(run) -> None:
    active = _call(
        get_nautobot_devices,
        run,
        {
            "nautobot_source_id": "itest",
            "inventory_type": "filter",
            "device_filter": _filter("status", "Active"),
        },
    )
    active_ctx = next(o for o in active if o.name == "success").context
    ids = [d.id for d in active_ctx.devices.values()][:3]

    outcomes = _call(
        get_nautobot_devices,
        run,
        {
            "nautobot_source_id": "itest",
            "inventory_type": "static",
            "device_ids": ids,
        },
    )
    ctx = next(o for o in outcomes if o.name == "success").context
    assert sorted(ctx.devices) == sorted(ids)


def test_get_nautobot_attributes(run) -> None:
    devices_outcome = _call(
        get_nautobot_devices,
        run,
        {
            "nautobot_source_id": "itest",
            "inventory_type": "filter",
            "device_filter": _filter("status", "Active"),
        },
    )
    ctx = next(o for o in devices_outcome if o.name == "success").context
    # keep it small
    small = WorkflowContext(
        run_id=ctx.run_id,
        workflow_id=ctx.workflow_id,
        devices=dict(list(ctx.devices.items())[:2]),
    )

    # list_of_attributes is a list of attribute-GROUP keys (see
    # attribute_bag.ATTR_TO_VAR), not individual custom-field names.
    outcomes = _call(
        get_nautobot_attributes,
        run,
        {"nautobot_source_id": "itest", "list_of_attributes": ["custom_fields"]},
        ctx=small,
        node_id="a1",
    )
    enriched = next(o for o in outcomes if o.name == "success").context
    assert len(enriched.devices) == len(small.devices)
    cfs = [
        d.attribute_bags.get("nautobot", {}).get("custom_fields", {})
        for d in enriched.devices.values()
    ]
    assert any("net" in cf or "checkmk_site" in cf for cf in cfs)


@pytest.mark.parametrize(
    "config",
    [
        {"nautobot_source_id": ""},
        {"nautobot_source_id": "no-such-source"},
    ],
)
def test_misconfig_raises_value_error(run, config) -> None:
    config = {"inventory_type": "filter", "device_filter": _filter("status", "Active"), **config}
    with pytest.raises(ValueError):
        _call(get_nautobot_devices, run, config)

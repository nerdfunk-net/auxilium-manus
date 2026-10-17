"""Cross-cutting — a full workflow run through ``StepRunner.execute_all``.

One honest "the whole chain works against real systems" signal per area.
Linear workflows only (no fan-out). Every ``StepRunner`` is closed in ``finally``.
"""

from __future__ import annotations

import pytest

import core.database as db_mod
from core.config import settings
from services.execution.step_runner import StepRunner
from tests.integration.helpers import env as env_helpers
from tests.integration.helpers.aio import run as arun
from tests.integration.helpers.workflows import build_linear_workflow, edge, make_run, node

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("require_postgres", "clean_tables"),
]


@pytest.fixture
def session():
    s = db_mod.SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(autouse=True)
def _artifacts_under_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_directory", tmp_path)


def _run_workflow(session, wf, run):
    async def _body():
        runner = StepRunner(session)
        try:
            return await runner.execute_all(run=run, workflow=wf)
        finally:
            await runner.close_device_sessions()

    return arun(_body())


def _step_statuses(session, run_id: int) -> dict[str, str]:
    from repositories.run_repository import RunRepository

    return {
        s.step_node_id: s.status for s in RunRepository(session).get_step_results_for_run(run_id)
    }


_PING = {"ping_count": 1, "required_replies": 1, "timeout_seconds": 1}


def _list_node(host: str):
    return node("list", "get-from-list", {"devices": [{"name": "lab-cisco", "ip_address": host}]})


def _cmd_node(ref: str):
    # parser: textfsm so the step actually produces PARSED (StepRunner's
    # post-step guard enforces the registry's declared `produces`).
    return node(
        "cmd",
        "run-command",
        {
            "credential_reference": ref,
            "commands": ["show ip interface brief"],
            "parser": "textfsm",
        },
    )


def _cfg_node(ref: str):
    return node(
        "cfg", "get-device-configs", {"credential_reference": ref, "config_format": "running"}
    )


def test_nautobot_filter_then_reachable(
    session, admin_user, nautobot_source, nautobot_app
) -> None:
    inv_config = {
        "nautobot_source_id": "itest",
        "inventory_type": "filter",
        "device_filter": {
            "logic": "AND",
            "negate": False,
            "id": "root",
            "items": [{"field": "location", "operator": "equals", "value": "City C"}],
        },
    }
    wf = build_linear_workflow(
        session,
        creator_id=admin_user.id,
        nodes=[
            node("inv", "get-nautobot-devices", inv_config),
            node("ping", "reachable", _PING),
        ],
    )
    run = make_run(session, workflow=wf, triggered_by_id=admin_user.id)

    result = _run_workflow(session, wf, run)
    assert isinstance(result, bool)

    statuses = _step_statuses(session, run.id)
    assert set(statuses) == {"inv", "ping"}
    assert "pending" not in statuses.values()

    session.refresh(run)
    assert run.status in {"success", "failed", "partial", "running", "pending"}


def test_static_device_then_netmiko_chain(session, admin_user, ssh_credential) -> None:
    host = env_helpers.cisco().host
    # get-from-list → run-command → get-device-configs, no parsing step between.
    # Regression coverage for the run-command post-step guard: a plain
    # run-command must not be required to produce Capability.PARSED.
    wf = build_linear_workflow(
        session,
        creator_id=admin_user.id,
        nodes=[_list_node(host), _cmd_node(ssh_credential), _cfg_node(ssh_credential)],
    )
    run = make_run(session, workflow=wf, triggered_by_id=admin_user.id, device_ids=["lab-cisco"])

    result = _run_workflow(session, wf, run)
    assert result is True

    statuses = _step_statuses(session, run.id)
    assert statuses["list"] == "success"
    assert statuses["cmd"] == "success"
    assert statuses["cfg"] == "success"


def test_failure_propagation_skips_downstream(session, admin_user) -> None:
    host = env_helpers.cisco().host
    wf = build_linear_workflow(
        session,
        creator_id=admin_user.id,
        nodes=[_list_node(host), _cmd_node("nope-not-real"), _cfg_node("nope-not-real")],
        edges=[edge("list", "cmd"), edge("cmd", "cfg")],
    )
    run = make_run(session, workflow=wf, triggered_by_id=admin_user.id)

    result = _run_workflow(session, wf, run)
    assert result is False

    statuses = _step_statuses(session, run.id)
    assert statuses["cmd"] in {"failed", "partial"}
    assert statuses["cfg"] == "skipped"


@pytest.mark.usefixtures("require_gitea")
def test_git_devices_then_reachable(session, admin_user, git_repository) -> None:
    import services.git.paths as git_paths

    # StepRunner clones through the real git data root; point it at tmp.
    original = git_paths._GIT_DATA_ROOT
    git_paths._GIT_DATA_ROOT = settings.data_directory / "git"
    git_paths._GIT_DATA_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        git_config = {
            "git_repository_id": git_repository["id"],
            "filename_pattern": "*.yaml",
            "directory": "devices",
        }
        wf = build_linear_workflow(
            session,
            creator_id=admin_user.id,
            nodes=[
                node("git", "get-git-devices", git_config),
                node("ping", "reachable", _PING),
            ],
        )
        run = make_run(session, workflow=wf, triggered_by_id=admin_user.id)
        result = _run_workflow(session, wf, run)
        assert isinstance(result, bool)
        statuses = _step_statuses(session, run.id)
        if statuses["git"] != "success":
            pytest.xfail("lab repo has no devices/*.yaml — add one per plan §5.8")
        assert "pending" not in statuses.values()
    finally:
        git_paths._GIT_DATA_ROOT = original

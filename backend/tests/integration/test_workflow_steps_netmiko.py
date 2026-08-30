"""Area 4 — Netmiko-backed workflow steps against the lab Cisco IOS device.

Direct executor calls (per plan §7): a persisted ``WorkflowRun`` attached to a
live session, a real ``FilesystemArtifactService`` under ``tmp_path``, and a real
``DeviceSessionPool``. Every pool is closed in the async body.

Requires: SSH reachable at ``CISCO_DEVICE`` with ``CISCO_DEVICE_USERNAME`` /
``CISCO_DEVICE_PASSWORD``, and the ``itest-ssh`` credential seeded.
"""

from __future__ import annotations

import pytest

import core.database as db_mod
from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import FilesystemArtifactService
from services.network.netmiko.session_pool import DeviceSessionPool
from tests.integration.helpers import env as env_helpers
from tests.integration.helpers.aio import run as arun
from tests.integration.helpers.workflows import build_linear_workflow, make_run, node
from workflow_steps.common.credential_resolver import CredentialReferenceNotFoundError
from workflow_steps.get_device_configs.executor import execute as get_device_configs
from workflow_steps.reachable.executor import execute as reachable
from workflow_steps.run_command.executor import execute as run_command

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("require_cisco_device", "require_postgres", "clean_tables"),
]

_UNROUTABLE = "192.0.2.123"  # RFC5737 TEST-NET-1


@pytest.fixture
def session():
    s = db_mod.SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def run(session, admin_user):
    wf = build_linear_workflow(
        session,
        creator_id=admin_user.id,
        nodes=[node("n1", "reachable", {})],
    )
    return make_run(session, workflow=wf, triggered_by_id=admin_user.id)


@pytest.fixture
def cisco_device():
    host = env_helpers.cisco().host
    return DeviceContext(
        id="d1",
        name="lab-cisco",
        hostname=host,
        primary_ip4=f"{host}/24",
        network_driver="cisco_ios",
        platform="cisco_ios",
        status=DeviceStatus.PENDING,
    )


def _ctx(run, *devices: DeviceContext) -> WorkflowContext:
    return WorkflowContext(
        run_id=run.uuid,
        workflow_id=str(run.workflow_id),
        devices={d.id: d for d in devices},
    )


# --------------------------------------------------------------------------- #
def test_reachable_success_and_failure(run, cisco_device, tmp_path) -> None:
    artifacts = FilesystemArtifactService(tmp_path)

    async def _body():
        pool = DeviceSessionPool(max_workers=2, enabled=True)
        try:
            ok = await reachable(
                config={"ping_count": 2, "required_replies": 1, "timeout_seconds": 2},
                context=_ctx(run, cisco_device),
                run=run,
                artifact_service=artifacts,
                node_id="n1",
                device_sessions=pool,
            )
            success = next(o for o in ok if o.name == "success")
            dev = success.context.devices["d1"]
            assert dev.parsed["n1.reachability"]["reachable"] is True
            assert dev.status == DeviceStatus.OK

            unreachable = cisco_device.model_copy(
                update={"hostname": _UNROUTABLE, "primary_ip4": f"{_UNROUTABLE}/32"}
            )
            bad = await reachable(
                config={"ping_count": 1, "required_replies": 1, "timeout_seconds": 1},
                context=_ctx(run, unreachable),
                run=run,
                artifact_service=artifacts,
                node_id="n1",
                device_sessions=pool,
            )
            failure = next(o for o in bad if o.name == "failure")
            assert "d1" in failure.context.devices
            codes = {e.code for e in failure.context.devices["d1"].errors}
            assert "unreachable" in codes
        finally:
            await pool.close()

    arun(_body())


def test_run_command_read_only_and_session_reuse(
    run, cisco_device, ssh_credential, tmp_path
) -> None:
    artifacts = FilesystemArtifactService(tmp_path)

    async def _body():
        pool = DeviceSessionPool(max_workers=2, enabled=True)
        try:
            cfg = {
                "credential_reference": ssh_credential,
                "commands": ["show version", "show ip interface brief"],
            }
            first = await run_command(
                config=cfg,
                context=_ctx(run, cisco_device),
                run=run,
                artifact_service=artifacts,
                node_id="c1",
                device_sessions=pool,
            )
            success = next(o for o in first if o.name == "success")
            dev = success.context.devices["d1"]
            results = dev.command_results["c1"]
            assert len(results) == 2
            for cr in results:
                text = artifacts.read_content(cr.output_ref.artifact_id)
                assert text.strip()

            # A second run-command node reuses the one pooled SSH session.
            await run_command(
                config={"credential_reference": ssh_credential, "commands": ["show clock"]},
                context=_ctx(run, cisco_device),
                run=run,
                artifact_service=artifacts,
                node_id="c2",
                device_sessions=pool,
            )
            assert len(pool._sessions) == 1
        finally:
            await pool.close()

    arun(_body())


def test_run_command_textfsm(run, cisco_device, ssh_credential, tmp_path) -> None:
    artifacts = FilesystemArtifactService(tmp_path)

    async def _body():
        pool = DeviceSessionPool(max_workers=2, enabled=True)
        try:
            outcomes = await run_command(
                config={
                    "credential_reference": ssh_credential,
                    "commands": ["show ip interface brief"],
                    "use_textfsm": True,
                },
                context=_ctx(run, cisco_device),
                run=run,
                artifact_service=artifacts,
                node_id="c1",
                device_sessions=pool,
            )
            success = next(o for o in outcomes if o.name == "success")
            cr = success.context.devices["d1"].command_results["c1"][0]
            import json

            parsed = json.loads(artifacts.read_content(cr.output_ref.artifact_id))
            assert isinstance(parsed, list)
        finally:
            await pool.close()

    arun(_body())


@pytest.mark.parametrize("config_format", ["running", "both"])
def test_get_device_configs(run, cisco_device, ssh_credential, tmp_path, config_format) -> None:
    artifacts = FilesystemArtifactService(tmp_path)

    async def _body():
        pool = DeviceSessionPool(max_workers=2, enabled=True)
        try:
            outcomes = await get_device_configs(
                config={
                    "credential_reference": ssh_credential,
                    "config_format": config_format,
                },
                context=_ctx(run, cisco_device),
                run=run,
                artifact_service=artifacts,
                node_id="g1",
                device_sessions=pool,
            )
            success = next(o for o in outcomes if o.name == "success")
            dev = success.context.devices["d1"]
            assert dev.running_config_ref is not None
            running = artifacts.read_content(dev.running_config_ref.artifact_id)
            assert running.lstrip().startswith("!") or "hostname" in running
            if config_format == "both":
                assert dev.startup_config_ref is not None
        finally:
            await pool.close()

    arun(_body())


def test_run_command_unknown_credential_raises(run, cisco_device, tmp_path) -> None:
    artifacts = FilesystemArtifactService(tmp_path)

    async def _body():
        pool = DeviceSessionPool(max_workers=2, enabled=True)
        try:
            with pytest.raises(CredentialReferenceNotFoundError):
                await run_command(
                    config={"credential_reference": "does-not-exist", "commands": ["show clock"]},
                    context=_ctx(run, cisco_device),
                    run=run,
                    artifact_service=artifacts,
                    node_id="c1",
                    device_sessions=pool,
                )
        finally:
            await pool.close()

    arun(_body())

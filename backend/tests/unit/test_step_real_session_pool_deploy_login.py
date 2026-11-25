"""Deploy and login steps against a real ``DeviceSessionPool`` (P-T, W13-01).

``deploy-rendered-template`` (Deploy rendered Template) pools its session by credential reference;
``login-successful`` (Login Successful) must open a disposable probe session that never enters the
pool. Only the Netmiko session object is faked.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from models.workflow_context import ArtifactRef, Capability, DeviceStatus
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import DeployResult
from services.network.netmiko.session_pool import DeviceSessionPool
from tests.unit._step_helpers import (
    call_step,
    make_context,
    make_device,
    make_run,
    patch_object_session,
    patch_ssh_credential,
)
from tests.unit.test_step_real_session_pool import FakeSession as _BaseSession
from workflow_steps.deploy_rendered_template.executor import execute as deploy
from workflow_steps.login_successful.executor import execute as login

_DEPLOY = "workflow_steps.deploy_rendered_template.executor"
_LOGIN = "workflow_steps.login_successful.executor"
_TEXT = "interface Gi0/0\n description test\n"


class FakeSession(_BaseSession):
    deployed: list[tuple[str, list[str], str]] = []
    saved: list[str] = []

    def deploy_config(self, commands: list[str], *, mode: str, **_kwargs: Any) -> DeployResult:
        FakeSession.deployed.append((self.host, list(commands), mode))
        return DeployResult(success=True, config_output="ok")

    def save_running_config(self) -> str:
        FakeSession.saved.append(self.host)
        return "saved"


@pytest_asyncio.fixture
async def pool() -> AsyncIterator[DeviceSessionPool]:
    _BaseSession.instances = []
    _BaseSession.refuse = set()
    FakeSession.deployed = []
    FakeSession.saved = []
    real = DeviceSessionPool(max_workers=2)
    with patch("services.network.netmiko.session_pool.NetmikoDeviceSession", FakeSession):
        yield real
    await real.close()


def _devices(*names: str, rendered: bool = False) -> Any:
    ref = ArtifactRef(artifact_id="a-1", kind="rendered_template", size_bytes=len(_TEXT))
    parsed = {
        "device_config": {
            "artifact_ref": ref.model_dump(mode="json"),
            "step_node_id": "render-1",
            "output_key": "device_config",
            "size_bytes": len(_TEXT),
            "kind": "rendered_template",
        }
    }
    return make_context(
        [
            make_device(
                n,
                name=n,
                primary_ip4=f"10.0.0.{i}/24",
                network_driver="cisco_ios",
                **(
                    {"parsed": parsed, "capabilities": {Capability.IDENTITY, Capability.PARSED}}
                    if rendered
                    else {}
                ),
            )
            for i, n in enumerate(names, start=1)
        ]
    )


@pytest.mark.asyncio
async def test_deploy_rendered_template_sends_through_the_pool_and_saves(
    pool: DeviceSessionPool,
) -> None:
    service = InMemoryArtifactService()
    config = {
        "credential_reference": "lab-ssh",
        "source_step_node_id": "render-1",
        "parsed_output_key": "device_config",
        "write_config_after_execution": True,
    }
    with (
        patch_ssh_credential(_DEPLOY),
        patch_object_session(),
        patch.object(service, "resolve", new=AsyncMock(return_value=_TEXT)),
    ):
        outcomes = await call_step(
            deploy,
            config,
            _devices("a", "b", rendered=True),
            run=make_run(),
            artifact_service=service,
            device_sessions=pool,
        )

    assert [o.name for o in outcomes] == ["success"]
    assert pool.stats()["created_total"] == 2
    assert sorted(h for h, _, _ in FakeSession.deployed) == ["10.0.0.1", "10.0.0.2"]
    assert all(
        cmds == ["interface Gi0/0", " description test"] for _, cmds, _ in FakeSession.deployed
    )
    assert sorted(FakeSession.saved) == ["10.0.0.1", "10.0.0.2"]
    assert all(d.status == DeviceStatus.OK for d in outcomes[0].context.devices.values())


@pytest.mark.asyncio
async def test_deploy_rendered_template_unreachable_device_fails_alone(
    pool: DeviceSessionPool,
) -> None:
    _BaseSession.refuse = {"10.0.0.2"}
    service = InMemoryArtifactService()
    config = {
        "credential_reference": "lab-ssh",
        "source_step_node_id": "render-1",
        "parsed_output_key": "device_config",
    }
    with (
        patch_ssh_credential(_DEPLOY),
        patch_object_session(),
        patch.object(service, "resolve", new=AsyncMock(return_value=_TEXT)),
    ):
        outcomes = await call_step(
            deploy,
            config,
            _devices("a", "b", "c", rendered=True),
            run=make_run(),
            artifact_service=service,
            device_sessions=pool,
        )

    by_name = {o.name: o.context.devices for o in outcomes}
    assert set(by_name["success"]) == {"a", "c"}
    assert set(by_name["failure"]) == {"b"}
    assert FakeSession.saved == []


@pytest.mark.asyncio
async def test_login_successful_probe_never_enters_the_pool(pool: DeviceSessionPool) -> None:
    _BaseSession.refuse = {"10.0.0.2"}
    with patch_ssh_credential(_LOGIN), patch_object_session():
        outcomes = await call_step(
            login,
            {"credential_reference": "lab-ssh"},
            _devices("a", "b"),
            run=make_run(),
            device_sessions=pool,
        )

    by_name = {o.name: o.context.devices for o in outcomes}
    assert set(by_name["success"]) == {"a"}
    assert set(by_name["failure"]) == {"b"}
    assert pool.stats()["created_total"] == 0
    assert all(not s.alive for s in _BaseSession.instances)
    assert len(_BaseSession.instances) == 2

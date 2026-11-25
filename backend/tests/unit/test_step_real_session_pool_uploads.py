"""The two SSH file-upload steps against a real ``DeviceSessionPool`` (P-T leftover, W13-01).

``upload-config`` and ``upload-binary`` reach the device through ``NetmikoService`` and the pool a
segment hands them. With a real pool and a fake Netmiko session a step that stops passing the pool,
or loses the credential reference that keys the session, is noticed; the unit tests patch both.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio

from models.workflow_context import Capability, DeviceContext, DeviceStatus
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import CommandResult, FileTransferResult
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
from workflow_steps.upload_binary.executor import execute as upload_binary
from workflow_steps.upload_config.executor import execute as upload_config

_UPLOAD_CONFIG = "workflow_steps.upload_config.executor"
_UPLOAD_BINARY = "workflow_steps.upload_binary.executor"
_CONTENT = "ntp server 192.168.178.10\n"
_IMAGE = b"\x00\xff\xfe" * 100


class FakeSession(_BaseSession):
    """Records the file each upload carried, read while the step's temp file still exists."""

    uploads: list[dict[str, Any]] = []

    def upload_file(self, **kwargs: Any) -> FileTransferResult:
        FakeSession.uploads.append(
            {
                "host": self.host,
                "dest_file": kwargs["dest_file"],
                "file_system": kwargs["file_system"],
                "bytes": Path(kwargs["local_path"]).read_bytes(),
            }
        )
        return FileTransferResult(success=True, file_transferred=True, file_verified=True)

    def send_commands(self, commands: list[str], **_kwargs: Any) -> CommandResult:
        self.sent.append(list(commands))
        (command,) = commands
        if command.startswith("dir "):
            return CommandResult(success=True, output="%Error opening flash:/x (No such file)")
        if command.startswith("verify /md5"):
            md5 = hashlib.md5(FakeSession.uploads[-1]["bytes"]).hexdigest()  # noqa: S324
            return CommandResult(success=True, output=f"verify /md5 (flash:x) = {md5}")
        raise AssertionError(command)


@pytest_asyncio.fixture
async def pool() -> AsyncIterator[DeviceSessionPool]:
    # ``instances`` and ``refuse`` are read through the base class by its own methods.
    _BaseSession.instances = []
    _BaseSession.refuse = set()
    FakeSession.uploads = []
    real = DeviceSessionPool(max_workers=2)
    with patch("services.network.netmiko.session_pool.NetmikoDeviceSession", FakeSession):
        yield real
    await real.close()


async def _config_devices(artifacts: InMemoryArtifactService, *names: str) -> Any:
    ref = await artifacts.store(
        content=_CONTENT,
        kind="updated_content",
        device_id="d",
        run_id="r",
        media_type="text/plain",
    )
    entry = {
        "artifact_ref": ref.model_dump(mode="json"),
        "step_node_id": "update-content-3",
        "output_key": "updated_content",
        "size_bytes": len(_CONTENT),
        "kind": "updated_content",
        "match_counts": {},
    }
    return make_context(
        [
            make_device(
                n,
                name=n,
                primary_ip4=f"10.0.0.{i}/24",
                network_driver="cisco_ios",
                parsed={"update-content-3": {"updated_content": entry}},
                capabilities={Capability.IDENTITY, Capability.PARSED},
            )
            for i, n in enumerate(names, start=1)
        ]
    )


_CONFIG_STEP = {
    "credential_reference": "lab-ssh",
    "content_source": "updated_content",
    "source_step_node_id": "update-content-3",
    "destination_filename": "new-config.cfg",
    "file_system": "bootflash:",
}


@pytest.mark.asyncio
async def test_upload_config_sends_the_artifact_through_the_pool(pool: DeviceSessionPool) -> None:
    artifacts = InMemoryArtifactService()
    context = await _config_devices(artifacts, "a", "b")
    with patch_ssh_credential(_UPLOAD_CONFIG) as credential, patch_object_session():
        outcomes = await call_step(
            upload_config,
            _CONFIG_STEP,
            context,
            run=make_run(id=9, triggered_by_id=4),
            artifact_service=artifacts,
            device_sessions=pool,
        )

    assert [o.name for o in outcomes] == ["success"]
    assert sorted(u["host"] for u in FakeSession.uploads) == ["10.0.0.1", "10.0.0.2"]
    assert {u["bytes"] for u in FakeSession.uploads} == {_CONTENT.encode()}
    assert {(u["dest_file"], u["file_system"]) for u in FakeSession.uploads} == {
        ("new-config.cfg", "bootflash:")
    }
    assert credential.call_args.kwargs["acting_user_id"] == 4
    # one live session per device, kept in the pool the step was given
    assert pool.stats()["created_total"] == 2
    assert sorted((s.host, s.alive) for s in _BaseSession.instances) == [
        ("10.0.0.1", True),
        ("10.0.0.2", True),
    ]


@pytest.mark.asyncio
async def test_upload_config_one_unreachable_device_fails_alone(pool: DeviceSessionPool) -> None:
    artifacts = InMemoryArtifactService()
    context = await _config_devices(artifacts, "a", "b")
    _BaseSession.refuse = {"10.0.0.2"}
    with patch_ssh_credential(_UPLOAD_CONFIG), patch_object_session():
        outcomes = await call_step(
            upload_config,
            _CONFIG_STEP,
            context,
            artifact_service=artifacts,
            device_sessions=pool,
        )

    by_name = {o.name: o for o in outcomes}
    assert list(by_name["success"].context.devices) == ["a"]
    failed = by_name["failure"].context.devices["b"]
    assert failed.status == DeviceStatus.FAILED
    assert [u["host"] for u in FakeSession.uploads] == ["10.0.0.1"]
    assert pool.stats()["created_total"] == 2  # the refused device still got a session


def _image_device(name: str, ip: str) -> DeviceContext:
    return make_device(name, name=name, primary_ip4=f"{ip}/24", network_driver="cisco_ios")


@pytest.mark.asyncio
async def test_upload_binary_copies_and_verifies_on_the_same_pooled_session(
    pool: DeviceSessionPool,
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve() / "repo"
        (root / "images").mkdir(parents=True)
        (root / "images" / "cat9k.bin").write_bytes(_IMAGE)
        scratch = Path(tmp).resolve() / "scratch"
        scratch.mkdir()

        async def _git_root(repository_id: int, stack: Any, **_kwargs: Any) -> Path:
            return root

        with (
            patch.object(tempfile, "tempdir", str(scratch)),
            patch(f"{_UPLOAD_BINARY}.resolve_git_root", new=_git_root),
            patch_ssh_credential(_UPLOAD_BINARY) as credential,
            patch_object_session(),
        ):
            outcomes = await call_step(
                upload_binary,
                {
                    "credential_reference": "lab-ssh",
                    "git_repository_id": 7,
                    "source_path": "images/cat9k.bin",
                    "file_system": "flash:",
                },
                make_context([_image_device("a", "10.0.0.1")]),
                run=make_run(id=9, triggered_by_id=4),
                device_sessions=pool,
            )

    assert [o.name for o in outcomes] == ["success"]
    assert [u["bytes"] for u in FakeSession.uploads] == [_IMAGE]
    assert pool.stats()["created_total"] == 1
    (session,) = _BaseSession.instances
    # existence check, then (after the copy) the checksum: all on the one pooled session
    assert [c[0].split()[0] for c in session.sent] == ["dir", "verify"]
    assert session.connects == 1
    assert credential.call_args.kwargs["acting_user_id"] == 4

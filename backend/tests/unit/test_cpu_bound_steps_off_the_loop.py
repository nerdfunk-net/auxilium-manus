"""``merge-content`` and ``log-attributes`` do their CPU- and disk-bound work off the event loop
(W4-15), as ``compare-data`` and ``get-from-config`` already do."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from models.workflow_context import (
    ArtifactRef,
    CommandResult,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from workflow_steps.log_attributes import executor as log_mod
from workflow_steps.merge_content import executor as merge_mod

pytestmark = pytest.mark.asyncio


class _Spy:
    """Replaces ``asyncio.to_thread``: records the function names, still runs them in a thread."""

    def __init__(self) -> None:
        self.names: list[str] = []
        self.threads: list[int] = []

    async def __call__(self, func, /, *args, **kwargs):
        self.names.append(getattr(func, "__name__", repr(func)))

        def _run():
            self.threads.append(threading.get_ident())
            return func(*args, **kwargs)

        return await asyncio.get_running_loop().run_in_executor(None, _run)


async def _merge_context() -> tuple[WorkflowContext, InMemoryArtifactService]:
    artifacts = InMemoryArtifactService()
    ref: ArtifactRef = await artifacts.store(
        content=json.dumps({"a": 1}),
        kind="command_output",
        device_id="d1",
        run_id="r",
        media_type="application/json",
    )
    device = DeviceContext(
        id="d1",
        name="d1",
        hostname="d1",
        status=DeviceStatus.OK,
        command_results={
            "src": [CommandResult(node_id="src", command="show x", success=True, output_ref=ref)]
        },
    )
    return WorkflowContext(run_id="r", workflow_id="w", devices={"d1": device}), artifacts


async def test_merge_content_merges_in_a_thread() -> None:
    context, artifacts = await _merge_context()
    spy = _Spy()
    with patch.object(merge_mod.asyncio, "to_thread", spy):
        outcomes = await merge_mod.execute(
            config={"merge_mode": "json_merged", "content_source": "command_output"},
            context=context,
            run=MagicMock(),
            artifact_service=artifacts,
            node_id="m1",
            device_sessions=MagicMock(),
        )

    assert [o.name for o in outcomes] == ["success"]
    assert spy.names == ["_merge_items_to_string"]
    assert spy.threads and spy.threads[0] != threading.get_ident()


async def test_log_attributes_renders_and_writes_in_a_thread(tmp_path: Path) -> None:
    context = WorkflowContext(
        run_id="r",
        workflow_id="w",
        devices={"d1": DeviceContext(id="d1", name="d1", hostname="d1")},
    )
    spy = _Spy()
    with (
        patch.object(log_mod.asyncio, "to_thread", spy),
        patch.object(log_mod, "log_attributes_root", return_value=tmp_path),
    ):
        outcomes = await log_mod.execute(
            config={"output_destination": "file", "filename": "out.json", "output_format": "json"},
            context=context,
            run=MagicMock(),
            artifact_service=InMemoryArtifactService(),
            node_id="l1",
            device_sessions=MagicMock(),
        )

    assert spy.names == ["render_snapshot_text", "_write_output_file"]
    written = (tmp_path / "w" / "r" / "out.json").read_text()
    assert json.loads(written)["devices"]["d1"]["name"] == "d1"
    assert outcomes[0].name == "success"


async def test_log_attributes_to_stdout_only_renders_in_a_thread() -> None:
    context = WorkflowContext(
        run_id="r",
        workflow_id="w",
        devices={"d1": DeviceContext(id="d1", name="d1", hostname="d1")},
    )
    spy = _Spy()
    with patch.object(log_mod.asyncio, "to_thread", spy):
        await log_mod.execute(
            config={"output_destination": "stdout", "output_format": "pretty_text"},
            context=context,
            run=MagicMock(),
            artifact_service=InMemoryArtifactService(),
            node_id="l1",
            device_sessions=MagicMock(),
        )

    assert spy.names == ["render_snapshot_text"]


async def test_log_attributes_appends_only_when_asked(tmp_path: Path) -> None:
    async def run(append: bool):
        context = WorkflowContext(
            run_id="r",
            workflow_id="w",
            devices={"d1": DeviceContext(id="d1", name="d1", hostname="d1")},
        )
        with patch.object(log_mod, "log_attributes_root", return_value=tmp_path):
            return await log_mod.execute(
                config={
                    "output_destination": "file",
                    "filename": "out.txt",
                    "output_format": "pretty_text",
                    "append": append,
                },
                context=context,
                run=MagicMock(),
                artifact_service=InMemoryArtifactService(),
                node_id="l1",
                device_sessions=MagicMock(),
            )

    await run(False)
    once = (tmp_path / "w" / "r" / "out.txt").read_text()
    await run(False)
    assert (tmp_path / "w" / "r" / "out.txt").read_text() == once
    await run(True)
    assert len((tmp_path / "w" / "r" / "out.txt").read_text()) > len(once)

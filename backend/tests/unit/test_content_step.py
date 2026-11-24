"""The shared runner of the content writers (filter-output, merge-content, update-content)."""

from __future__ import annotations

import pytest

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from workflow_steps.common.content_resolver import list_exportable_content
from workflow_steps.common.content_step import StoredContent, run_content_step
from workflow_steps.common.device_runner import Fail

pytestmark = pytest.mark.asyncio


def _device(device_id: str) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        status=DeviceStatus.OK,
        capabilities={Capability.IDENTITY},
    )


def _context(*ids: str) -> WorkflowContext:
    return WorkflowContext(
        run_id="run-9",
        workflow_id="w",
        devices={i: _device(i) for i in ids},
        metadata={"keep": 1},
    )


async def _run(context, transform, *, kind="filtered_output", overrides=None, metadata=None):
    artifacts = InMemoryArtifactService()
    outcomes = await run_content_step(
        context,
        step_id="some-step",
        node_id="n7",
        kind=kind,
        transform=transform,
        artifact_service=artifacts,
        metadata_prefix="some",
        metadata=metadata,
        code_overrides=overrides,
    )
    return {o.name: o for o in outcomes}, artifacts


async def test_a_stored_result_is_the_entry_the_consumer_reads() -> None:
    async def transform(device_id: str, device: DeviceContext) -> StoredContent:
        return StoredContent(text="héllo\n", media_type="text/plain", entry={"match_counts": [2]})

    outcomes, artifacts = await _run(_context("d1"), transform)
    device = outcomes["success"].context.devices["d1"]
    entry = device.parsed["n7"]["filtered_output"]
    assert entry["kind"] == "filtered_output"
    assert entry["output_key"] == "filtered_output"
    assert entry["step_node_id"] == "n7"
    assert entry["size_bytes"] == len("héllo\n".encode())
    assert entry["match_counts"] == [2]
    assert device.status == DeviceStatus.OK
    assert Capability.PARSED in device.capabilities
    assert Capability.IDENTITY in device.capabilities
    (item,) = list_exportable_content(
        device, content_source="filtered_output", source_step_node_id="n7", step_id="s"
    )
    assert item.media_type == "text/plain"
    assert await artifacts.resolve(item.artifact_ref) == "héllo\n"


async def test_a_pending_device_leaves_the_step_ok() -> None:
    async def transform(device_id: str, device: DeviceContext) -> StoredContent:
        return StoredContent(text="x", media_type="text/plain")

    context = _context("d1")
    pending = context.devices["d1"].model_copy(update={"status": DeviceStatus.PENDING})
    context = context.model_copy(update={"devices": {"d1": pending}})
    outcomes, _ = await _run(context, transform)
    assert outcomes["success"].context.devices["d1"].status == DeviceStatus.OK


@pytest.mark.parametrize("kind", ["merged_content", "filtered_output", "updated_content"])
async def test_each_kind_round_trips(kind: str) -> None:
    async def transform(device_id: str, device: DeviceContext) -> StoredContent:
        return StoredContent(text="x", media_type="application/json")

    outcomes, _ = await _run(_context("d1"), transform, kind=kind)
    device = outcomes["success"].context.devices["d1"]
    (item,) = list_exportable_content(
        device, content_source=kind, source_step_node_id="n7", step_id="s"
    )
    assert (item.kind, item.media_type) == (kind, "application/json")
    assert item.artifact_ref.kind == kind


async def test_the_artifact_is_stored_for_the_device_and_run() -> None:
    async def transform(device_id: str, device: DeviceContext) -> StoredContent:
        return StoredContent(text="x", media_type="text/plain")

    artifacts = InMemoryArtifactService()
    calls: list[dict] = []
    real = artifacts.store

    async def spy(**kwargs):
        calls.append(kwargs)
        return await real(**kwargs)

    artifacts.store = spy  # type: ignore[method-assign]
    await run_content_step(
        _context("d1"),
        step_id="s",
        node_id="n7",
        kind="merged_content",
        transform=transform,
        artifact_service=artifacts,
        metadata_prefix="m",
    )
    assert calls == [
        {
            "content": "x",
            "kind": "merged_content",
            "device_id": "d1",
            "run_id": "run-9",
            "media_type": "text/plain",
        }
    ]


async def test_a_step_sentence_is_kept_and_any_other_error_is_the_class_name() -> None:
    async def transform(device_id: str, device: DeviceContext) -> StoredContent:
        if device_id == "bad-value":
            raise ValueError("No content found for x")
        if device_id == "bad-other":
            raise KeyError("secret text")
        return StoredContent(text="ok", media_type="text/plain")

    outcomes, _ = await _run(_context("good", "bad-value", "bad-other"), transform)
    assert list(outcomes["success"].context.devices) == ["good"]
    failed = outcomes["failure"].context.devices
    assert failed["bad-value"].errors[-1].message == "No content found for x"
    assert failed["bad-value"].errors[-1].code == "valueerror"
    assert failed["bad-other"].errors[-1].message == "KeyError"
    assert failed["bad-other"].errors[-1].step_id == "some-step"
    assert failed["bad-other"].errors[-1].node_id == "n7"
    assert failed["bad-other"].status == DeviceStatus.FAILED


class _Nothing(ValueError):  # noqa: N818
    pass


async def test_a_code_override_keeps_the_sentence_and_the_record() -> None:
    async def transform(device_id: str, device: DeviceContext) -> StoredContent:
        raise _Nothing("nothing to merge here")

    outcomes, _ = await _run(_context("d1"), transform, overrides={_Nothing: "nothing_to_merge"})
    error = outcomes["failure"].context.devices["d1"].errors[-1]
    assert error.code == "nothing_to_merge"
    assert error.message == "nothing to merge here"
    assert error.failure is not None
    assert error.failure.exception_type == "_Nothing"


async def test_a_fail_value_is_recorded_as_given() -> None:
    async def transform(device_id: str, device: DeviceContext) -> Fail:
        return Fail("my_code", "my message")

    outcomes, _ = await _run(_context("d1"), transform)
    error = outcomes["failure"].context.devices["d1"].errors[-1]
    assert (error.code, error.message) == ("my_code", "my message")


async def test_counts_and_metadata_are_on_both_outcomes() -> None:
    async def transform(device_id: str, device: DeviceContext) -> StoredContent:
        if device_id == "bad":
            raise ValueError("no")
        return StoredContent(text="ok", media_type="text/plain")

    outcomes, _ = await _run(
        _context("a", "b", "bad"), transform, metadata={"n7.some_mode": "text_plain"}
    )
    for outcome in outcomes.values():
        assert outcome.context.metadata == {
            "keep": 1,
            "n7.some_mode": "text_plain",
            "n7.some_success_count": 2,
            "n7.some_failure_count": 1,
        }


async def test_no_failure_outcome_without_a_failed_device() -> None:
    async def transform(device_id: str, device: DeviceContext) -> StoredContent:
        return StoredContent(text="ok", media_type="text/plain")

    outcomes, _ = await _run(_context("a"), transform)
    assert list(outcomes) == ["success"]


async def test_no_devices_is_a_plain_success_and_runs_nothing() -> None:
    async def transform(device_id: str, device: DeviceContext) -> StoredContent:
        raise AssertionError("not called")

    context = _context()
    outcomes, artifacts = await _run(context, transform)
    assert list(outcomes) == ["success"]
    assert outcomes["success"].context is context


async def test_the_input_context_is_not_changed() -> None:
    async def transform(device_id: str, device: DeviceContext) -> StoredContent:
        return StoredContent(text="ok", media_type="text/plain")

    context = _context("a")
    await _run(context, transform)
    assert context.metadata == {"keep": 1}
    assert context.devices["a"].parsed == {}


@pytest.mark.parametrize(
    ("step", "config", "prefix", "extra", "code"),
    [
        (
            "merge_content",
            {"source_step_node_ids": ["n"], "content_source": "merged_content"},
            "merged",
            {"n7.merged_content_mode": "text_sectioned"},
            "nothing_to_merge",
        ),
        (
            "update_content",
            {"replace_rules": [{"pattern": "x"}]},
            "update_content",
            {},
            "valueerror",
        ),
        (
            "filter_output",
            {"source_step_node_id": "n", "filter_rules": [{"pattern": "x"}]},
            "filter",
            {},
            "valueerror",
        ),
    ],
)
async def test_each_step_keeps_its_metadata_keys_and_failure_codes(
    step: str, config: dict, prefix: str, extra: dict, code: str
) -> None:
    import importlib
    from unittest.mock import MagicMock

    executor = importlib.import_module(f"workflow_steps.{step}.executor")
    outcomes = await executor.execute(
        config=config,
        context=_context("d1"),
        run=MagicMock(),
        artifact_service=InMemoryArtifactService(),
        node_id="n7",
        device_sessions=MagicMock(),
    )
    by_name = {o.name: o for o in outcomes}
    failed = by_name["failure"].context.devices["d1"]
    assert failed.errors[-1].code == code
    for outcome in by_name.values():
        assert outcome.context.metadata == {
            "keep": 1,
            "n7." + prefix + "_success_count": 0,
            "n7." + prefix + "_failure_count": 1,
            **extra,
        }

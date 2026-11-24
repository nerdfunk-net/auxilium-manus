"""W4-02: `compare-data` (Compare Data) checks its config once and keeps every device's result.

* a bad `reference_location` / missing `git_repository_id` fails the step before any device
  (it used to fail every device with `comparison_error`),
* an unpopulated `content_source` takes the `get_config()` default and a bad one names this step,
* a diff or artifact-store error on one mismatching device fails that device, not the step.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from models.workflow_context import ArtifactRef, Capability
from services.artifacts import InMemoryArtifactService
from tests.unit._step_helpers import call_step, make_context, make_device
from workflow_steps.compare_data import executor as mod


def _device(device_id: str):
    return make_device(
        device_id,
        running_config_ref=ArtifactRef(artifact_id=f"a-{device_id}", kind="running_config"),
        capabilities={Capability.IDENTITY, Capability.RUNNING_CONFIG},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("config", "needle"),
    [
        ({"reference_location": "ftp"}, "reference_location"),
        ({"reference_location": "git"}, "git_repository_id"),
        ({"reference_location": "git", "git_repository_id": "7.9"}, "git_repository_id"),
        ({"pull_before_read": "nope"}, "pull_before_read"),
        ({"content_source": "bogus"}, "compare-data: content_source"),
    ],
)
async def test_a_config_error_fails_the_step_not_every_device(
    config: dict[str, object], needle: str
) -> None:
    context = make_context([_device("d1"), _device("d2")])
    with pytest.raises(ValueError, match=needle):
        await call_step(mod.execute, config, context)


def test_an_unpopulated_content_source_takes_the_default() -> None:
    assert mod._parse_compare_config({}).content_source == "running_config"


@pytest.mark.asyncio
async def test_a_store_error_on_a_mismatch_fails_only_that_device(tmp_path: Path) -> None:
    references = tmp_path / "references"
    references.mkdir()
    (references / "d1.cfg").write_text("reference one\n", encoding="utf-8")
    (references / "d2.cfg").write_text("same\n", encoding="utf-8")
    artifacts = InMemoryArtifactService()

    async def resolve(ref: ArtifactRef) -> str:
        return "different\n" if ref.artifact_id == "a-d1" else "same\n"

    with (
        patch("workflow_steps.common.reference_reader.settings") as settings_mock,
        patch.object(artifacts, "resolve", new=AsyncMock(side_effect=resolve)),
        patch.object(artifacts, "store", new=AsyncMock(side_effect=RuntimeError("disk full /x"))),
    ):
        settings_mock.data_directory = tmp_path
        outcomes = await call_step(
            mod.execute,
            {"content_source": "running_config"},
            make_context([_device("d1"), _device("d2")]),
            artifact_service=artifacts,
        )
    by_name = {outcome.name: outcome.context for outcome in outcomes}
    assert list(by_name["match"].devices) == ["d2"]
    assert list(by_name["failure"].devices) == ["d1"]
    error = by_name["failure"].devices["d1"].errors[-1]
    assert "disk full" not in error.message
    assert error.failure is not None

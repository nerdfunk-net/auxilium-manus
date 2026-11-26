"""W7-04 (P-E): the pyATS steps keep the classification of a shim failure.

``PyATSError.failure`` says "timeout", "auth_failed", "server_error", ... without copying text;
the batch path used to flatten the exception into ``str(exc)`` and drop it, so a failure branch
could not tell the shim being down from a device refusing the login. A device-level error from
the shim (whatever Unicon printed) keeps its text, capped, with a generic ``command_error``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.failure import FailureInfo
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from tests.unit._step_helpers import make_device
from workflow_steps.common import pyats_batch
from workflow_steps.common.device_runner import Fail
from workflow_steps.compare_pyats_snapshot import executor as compare_mod
from workflow_steps.configure_replace_config import shim_jobs as replace_mod
from workflow_steps.get_pyats_running_config import executor as running_mod
from workflow_steps.get_pyats_snapshot import executor as snapshot_mod

_SECRET = "driver text 10.9.9.9 token=abc"


async def _batched(error: BaseException) -> dict[str, Any]:
    shim = MagicMock()
    shim.limits = AsyncMock(side_effect=RuntimeError("no limits"))
    shim.run_job = AsyncMock(side_effect=error)
    return await pyats_batch.run_batched(
        shim=shim,
        credentials=MagicMock(),
        operation="parse",
        commands=["show version"],
        device_group=[("a", {"name": "a"})],
    )


# --- run_batched -----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (PyATSAPIError("shim timed out", code="timeout"), "timeout"),
        (PyATSAPIError("shim said no", http_status=401), "auth_failed"),
        (PyATSAPIError("shim broke", http_status=503), "server_error"),
        (PyATSValidationError("bad testbed"), "bad_request"),
    ],
)
async def test_a_shim_error_keeps_its_classification(error: BaseException, kind: str) -> None:
    result = (await _batched(error))["a"]

    assert result["success"] is False
    assert result["error"] == str(error)
    assert result["failure"].kind == kind


@pytest.mark.asyncio
async def test_an_unexpected_chunk_error_is_an_internal_error_with_the_class_name() -> None:
    result = (await _batched(ValueError(_SECRET)))["a"]

    assert result["error"] == "ValueError"
    assert _SECRET not in str(result)
    assert result["failure"].kind == "internal_error"
    assert result["failure"].exception_type == "ValueError"


# --- the device-level helper -----------------------------------------------------------------


def test_a_device_level_error_keeps_its_text_capped_and_is_a_command_error() -> None:
    message, failure = pyats_batch.shim_device_failure({"success": False, "error": "x" * 2000})

    assert message == "x" * 300 + "…"
    assert failure.kind == "command_error"
    assert failure.phase == "command"


def test_a_short_device_level_error_is_not_changed() -> None:
    message, _failure = pyats_batch.shim_device_failure({"success": False, "error": "login failed"})

    assert message == "login failed"


def test_a_missing_result_gets_the_generic_sentence() -> None:
    message, failure = pyats_batch.shim_device_failure(None)

    assert message == "pyATS shim reported failure for this device"
    assert failure.kind == "command_error"


def test_a_carried_failure_wins_over_the_generic_one() -> None:
    carried = FailureInfo(phase="api", kind="timeout", retryable=True)

    _message, failure = pyats_batch.shim_device_failure(
        {"success": False, "error": "e", "failure": carried}
    )

    assert failure is carried


# --- the steps copy it onto the device failure -----------------------------------------------


def test_get_running_config_fails_with_the_carried_failure() -> None:
    carried = FailureInfo(phase="api", kind="timeout", retryable=True)

    fail = running_mod._shape_result(
        node_id="n1",
        device_id="a",
        device=make_device("a"),
        output_key="k",
        result={"success": False, "error": "shim timed out", "failure": carried},
    )

    assert isinstance(fail, Fail)
    assert (fail.code, fail.message, fail.failure) == ("device_error", "shim timed out", carried)


def test_get_running_config_device_error_is_a_capped_command_error() -> None:
    fail = running_mod._shape_result(
        node_id="n1",
        device_id="a",
        device=make_device("a"),
        output_key="k",
        result={"success": False, "error": "y" * 2000},
    )

    assert isinstance(fail, Fail)
    assert len(fail.message) <= pyats_batch.MAX_SHIM_TEXT + 1
    assert fail.failure is not None
    assert fail.failure.kind == "command_error"


@pytest.mark.asyncio
async def test_get_snapshot_fails_with_the_carried_failure() -> None:
    carried = FailureInfo(phase="auth", kind="auth_failed")

    fail = await snapshot_mod._shape_and_store_result(
        device_id="a",
        device=make_device("a"),
        output_key="k",
        features=["bgp"],
        run_id="r",
        node_id="n",
        artifact_service=MagicMock(),
        result={"success": False, "error": "shim said no", "failure": carried},
    )

    assert isinstance(fail, Fail)
    assert fail.failure is carried
    assert fail.message == "shim said no"


@pytest.mark.asyncio
async def test_get_snapshot_device_error_is_a_capped_command_error() -> None:
    fail = await snapshot_mod._shape_and_store_result(
        device_id="a",
        device=make_device("a"),
        output_key="k",
        features=["bgp"],
        run_id="r",
        node_id="n",
        artifact_service=MagicMock(),
        result={"success": False, "error": "z" * 2000},
    )

    assert isinstance(fail, Fail)
    assert len(fail.message) <= pyats_batch.MAX_SHIM_TEXT + 1
    assert fail.failure is not None
    assert fail.failure.kind == "command_error"


# --- compare-pyats-snapshot ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_shim_error_carries_the_failure() -> None:
    shim = MagicMock()
    shim.diff = AsyncMock(side_effect=PyATSAPIError("shim timed out", code="timeout"))
    with patch.object(compare_mod.service_factory, "get_pyats_app_service", return_value=shim):
        fail = await compare_mod._diff_features(
            device=make_device("a"),
            device_id="a",
            node_id="n",
            features=["bgp"],
            live_snapshot={"bgp": {"success": True, "data": {"x": 1}}},
            reference_snapshot={"bgp": {"success": True, "data": {"x": 2}}},
            exclude_keys=[],
            use_snapshot_excludes=False,
            shim_credentials=MagicMock(),
        )

    assert isinstance(fail, Fail)
    assert fail.code == "shim_error"
    assert fail.failure is not None
    assert fail.failure.kind == "timeout"


@pytest.mark.asyncio
async def test_compare_reference_error_hides_the_text_and_records_an_internal_error() -> None:
    with patch.object(compare_mod, "read_reference_text", AsyncMock(side_effect=OSError(_SECRET))):
        fail = await compare_mod._load_reference_snapshot(
            device=make_device("a"),
            device_id="a",
            node_id="n",
            item=MagicMock(extra={}),
            config={"filename_template": "{device.name}.json"},
            context_run_id="r",
        )

    assert isinstance(fail, Fail)
    assert fail.code == "reference_error"
    assert fail.message == "OSError"
    assert _SECRET not in repr(fail)
    assert fail.failure is not None
    assert fail.failure.kind == "internal_error"


# --- configure-replace-config ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_configure_replace_device_level_error_carries_a_command_error() -> None:
    shim = MagicMock()
    shim.run_job = AsyncMock(
        return_value={"results": {"a": {"success": False, "error": "w" * 2000}}}
    )

    result = await replace_mod.run_shim_job(
        shim,
        MagicMock(),
        operation="run",
        shim_device={"name": "a"},
        commands=["x"],
        timeout=120.0,
    )

    assert result.ok is False
    assert len(str(result.error)) <= pyats_batch.MAX_SHIM_TEXT + 1
    assert result.failure is not None
    assert result.failure.kind == "command_error"

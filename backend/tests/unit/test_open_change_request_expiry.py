"""``expires_after_hours`` of open-change-request (P-T write-first for W9-05).

The registry says "0 disables expiry"; the executor reads ``int(value or 168)``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tests.unit._step_helpers import call_step, make_context, make_device, make_run
from workflow_steps.open_change_request import executor as mod


def _expires_passed(config: dict[str, Any]) -> Any:
    service = MagicMock()
    with (
        patch.object(mod, "get_db_session", return_value=MagicMock()),
        patch(
            "services.change_requests.change_request_service.ChangeRequestService",
            return_value=service,
        ),
    ):
        mod._create_change_request(
            config=config,
            context=make_context([make_device("d1")]),
            run=make_run(device_ids=["d1"]),
            repository_id=1,
            staged={"base_ref": "main", "commit_sha": "c0ffee"},
            naming=mod._Naming(branch="b", commit_message="m", title="t"),
            device_paths={},
            diff_ref=MagicMock(artifact_id=None),
            diff_stats={},
        )
    return service.create_from_step.call_args.kwargs["expires_after_hours"]


@pytest.mark.parametrize(("raw", "expected"), [(None, 168), ("", 168), (24, 24), ("48", 48)])
def test_expiry_defaults_to_a_week_and_takes_whole_hours(raw: Any, expected: int) -> None:
    assert _expires_passed({"expires_after_hours": raw}) == expected


def test_zero_disables_expiry() -> None:
    assert _expires_passed({"expires_after_hours": 0}) == 0


@pytest.mark.parametrize("raw", ["abc", True, 7.9, -1])
def test_a_bad_value_is_a_config_error(raw: Any) -> None:
    with pytest.raises(ValueError, match="expires_after_hours"):
        _expires_passed({"expires_after_hours": raw})


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["abc", True])
async def test_a_bad_value_fails_before_anything_is_pushed(raw: Any) -> None:
    with patch.object(mod, "load_git_repository") as load:
        outcomes = await call_step(
            mod.execute,
            {"git_repository_id": 1, "expires_after_hours": raw},
            make_context([make_device("d1")]),
        )

    failed = next(o for o in outcomes if o.name == "failure").context.devices["d1"]
    assert "expires_after_hours" in failed.errors[-1].message
    load.assert_not_called()

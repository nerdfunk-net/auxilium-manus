"""W7-14: the ACL check judges every matching filter; the path check refuses invert_search."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.workflow_context import WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.batfish.credentials import BatfishConnection
from workflow_steps.batfish_acl_check import executor as acl
from workflow_steps.batfish_path_check import executor as path
from workflow_steps.common.batfish_context import store_batfish_snapshot

_ACL = {"node": "R1", "filter_name": "/ACL.*/", "dst_ips": "10.0.0.1"}


def _context() -> WorkflowContext:
    return store_batfish_snapshot(
        WorkflowContext(run_id="u", workflow_id="7"),
        connection=BatfishConnection(host="b", port=9996),
        network="n",
        snapshot="s",
    )


async def _acl(actions: list[str]):
    with patch("workflow_steps.batfish_acl_check.executor.service_factory") as sf:
        batfish = MagicMock()
        batfish.test_filters = AsyncMock(return_value=[{"Action": a} for a in actions])
        sf.get_batfish_app_service.return_value = batfish
        return await acl.execute(
            config=_ACL,
            context=_context(),
            run=MagicMock(id=1),
            artifact_service=InMemoryArtifactService(),
            node_id="n1",
            device_sessions=MagicMock(),
        )


@pytest.mark.asyncio
async def test_all_filters_permit_is_permit_with_filter_count() -> None:
    outcomes = await _acl(["PERMIT", "permit"])
    assert outcomes[0].name == "permit"
    assert outcomes[0].summary == "permit (PERMIT), 2 filters"


@pytest.mark.asyncio
async def test_one_denying_filter_denies_even_when_the_first_permits() -> None:
    outcomes = await _acl(["PERMIT", "DENY"])
    assert outcomes[0].name == "deny"
    assert outcomes[0].summary == "deny (DENY), 2 filters"


@pytest.mark.asyncio
async def test_unexpected_or_blank_action_denies() -> None:
    blank = (await _acl(["PERMIT", ""]))[0]
    assert (blank.name, blank.summary) == ("deny", "deny (DENY), 2 filters")
    assert (await _acl(["PERMIT", "weird"]))[0].summary == "deny (WEIRD), 2 filters"


@pytest.mark.asyncio
async def test_single_filter_summary_is_unchanged() -> None:
    assert (await _acl(["DENY"]))[0].summary == "deny (DENY)"


async def _path(config: dict):
    with patch("workflow_steps.batfish_path_check.executor.service_factory") as sf:
        batfish = MagicMock()
        batfish.reachability = AsyncMock(return_value=[{"Flow": "x"}])
        sf.get_batfish_app_service.return_value = batfish
        outcomes = await path.execute(
            config=config,
            context=_context(),
            run=MagicMock(id=1),
            artifact_service=InMemoryArtifactService(),
            node_id="n1",
            device_sessions=MagicMock(),
        )
    return outcomes, batfish


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, "true", "1"])
async def test_path_check_refuses_invert_search(value) -> None:
    with pytest.raises(ValueError, match="invert_search"):
        await _path({"start_node": "R1", "invert_search": value})


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{}, {"invert_search": False}, {"invert_search": "false"}])
async def test_path_check_without_invert_search_runs_a_plain_search(config) -> None:
    outcomes, batfish = await _path({"start_node": "R1", **config})
    assert outcomes[0].name == "reachable"
    assert batfish.reachability.call_args.kwargs["invertSearch"] is False

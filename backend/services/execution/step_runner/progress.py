"""Progress reporting for fan-out child (``DeviceGroupExecution``) subgraph walks.

Children write no ``WorkflowStepResult`` rows — the parent aggregates them after
every child finishes — so without this the UI cannot show what a child is doing
while it runs. A sink receives per-node state changes and persists them on the
child's ``WorkflowRunDeviceGroup`` row.

Progress is strictly best-effort: a failing sink must never fail a device run.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from repositories.run_repository import RunRepository

logger = logging.getLogger(__name__)


class SubgraphProgressSink(Protocol):
    async def node_started(self, node_id: str) -> None: ...

    async def node_finished(self, node_id: str, state: str) -> None:
        """``state`` is one of success | partial | failed | skipped."""
        ...


class DeviceGroupProgressSink:
    """Persists node states on one device group row.

    Siblings in a topological wave share one SQLAlchemy ``Session`` and call the
    sink concurrently; the lock serialises those writes (a Session is not safe
    for interleaved use).
    """

    def __init__(self, repo: RunRepository, *, run_id: int, child_index: int) -> None:
        self._repo = repo
        self._run_id = run_id
        self._child_index = child_index
        self._lock = asyncio.Lock()
        self._states: dict[str, str] = {}

    def overall_status(self) -> str:
        """Group status implied by the node states reported so far:
        failed if any node failed, else partial if any was partial, else success."""
        states = set(self._states.values())
        if "failed" in states:
            return "failed"
        if "partial" in states:
            return "partial"
        return "success"

    async def node_started(self, node_id: str) -> None:
        await self._set(node_id, "running")

    async def node_finished(self, node_id: str, state: str) -> None:
        await self._set(node_id, state)

    async def _set(self, node_id: str, state: str) -> None:
        async with self._lock:
            self._states = {**self._states, node_id: state}
            try:
                self._repo.set_device_group_node_state(
                    run_id=self._run_id,
                    child_index=self._child_index,
                    node_id=node_id,
                    state=state,
                )
            except Exception:
                logger.warning(
                    "Failed to record device-group progress run_id=%s child_index=%s node_id=%s",
                    self._run_id,
                    self._child_index,
                    node_id,
                    exc_info=True,
                )


async def report_node_started(sink: SubgraphProgressSink | None, node_id: str) -> None:
    if sink is None:
        return
    try:
        await sink.node_started(node_id)
    except Exception:
        logger.warning("Progress sink node_started failed node_id=%s", node_id, exc_info=True)


async def report_node_finished(sink: SubgraphProgressSink | None, node_id: str, state: str) -> None:
    if sink is None:
        return
    try:
        await sink.node_finished(node_id, state)
    except Exception:
        logger.warning("Progress sink node_finished failed node_id=%s", node_id, exc_info=True)

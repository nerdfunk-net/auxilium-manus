"""Shared builders and typed fakes for workflow-step tests (P-T, W13-01/03/05).

Flat module next to ``_git_helpers.py`` and friends (decision D4: no ``steps/`` package).
Adopt it in the files a refactoring touches; there is no mass rewrite of the old helpers.

* ``make_run`` / ``make_pool`` return ``MagicMock(spec=...)`` fakes: a typo in an attribute the
  step reads (``run.run_inputz``) raises ``AttributeError`` instead of returning a new mock.
* ``patch_object_session`` is needed because ``sqlalchemy.orm.object_session`` refuses a
  ``spec`` mock; it patches the name in the step module (or modules) that calls it.
* ``strict_xfail`` marks a test that fails on today's code because of a known finding; it
  turns into a plain test when the fix lands (``strict=True``: an unexpected pass fails).
* ``FakeNautobotGraphQL`` answers the device lookups of ``common/nautobot_resolve.py`` (name,
  case-insensitive name, primary IPv4) from a list of devices, so a step test runs the real
  resolver instead of patching ``resolve_nautobot_device_id`` (W13-06).
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.session_pool import DeviceSessionPool

DEFAULT_NODE_ID = "node-1"


def make_device(
    device_id: str = "d1",
    *,
    name: str | None = None,
    hostname: str | None = None,
    status: DeviceStatus = DeviceStatus.OK,
    **fields: Any,
) -> DeviceContext:
    """One device; ``name`` and ``hostname`` default to the id."""
    fields.setdefault("capabilities", {Capability.IDENTITY})
    return DeviceContext(
        id=device_id,
        name=name or device_id,
        hostname=hostname or name or device_id,
        status=status,
        **fields,
    )


def make_context(
    devices: Iterable[DeviceContext] = (),
    *,
    run_id: str = "run-1",
    workflow_id: str = "wf-1",
    **metadata: Any,
) -> WorkflowContext:
    """A context holding ``devices`` keyed by id; ``metadata`` keys land in ``context.metadata``."""
    return WorkflowContext(
        run_id=run_id,
        workflow_id=workflow_id,
        devices={device.id: device for device in devices},
        metadata=dict(metadata),
    )


def make_run(**attrs: Any) -> MagicMock:
    """A ``WorkflowRun`` stand-in that rejects attributes the model does not have."""
    run = MagicMock(spec=WorkflowRun)
    defaults: dict[str, Any] = {
        "id": 1,
        "uuid": "run-uuid-1",
        "workflow_id": 1,
        "triggered_by_id": 1,
        "run_inputs": {},
        "change_request_id": None,
    }
    for key, value in {**defaults, **attrs}.items():
        setattr(run, key, value)
    return run


def make_pool() -> MagicMock:
    """A ``DeviceSessionPool`` stand-in; calling a method the pool lacks raises."""
    return MagicMock(spec=DeviceSessionPool)


async def call_step(
    execute: Callable[..., Any],
    config: dict[str, Any],
    context: WorkflowContext,
    *,
    run: Any = None,
    artifact_service: Any = None,
    node_id: str = DEFAULT_NODE_ID,
    device_sessions: Any = None,
) -> list[StepOutcome]:
    """``execute(...)`` with the six keywords every step takes, typed fakes as defaults."""
    return await execute(
        config=config,
        context=context,
        run=run if run is not None else make_run(),
        artifact_service=artifact_service
        if artifact_service is not None
        else InMemoryArtifactService(),
        node_id=node_id,
        device_sessions=device_sessions if device_sessions is not None else make_pool(),
    )


@contextmanager
def patch_ssh_credential(
    module: str, credentials: tuple[str, str] = ("admin", "secret")
) -> Generator[MagicMock]:
    """Replace ``resolve_ssh_credential`` in ``module`` (a dotted path); yields the mock.

    Keep one explicit assertion on ``mock.call_args`` per step (user id, reference).
    """
    with patch(f"{module}.resolve_ssh_credential", return_value=credentials) as mock:
        yield mock


@contextmanager
def patch_object_session(*, db: Any = None) -> Generator[Any]:
    """Make the session a step gets from its run (``require_session``) a MagicMock, or ``db``."""
    session = db if db is not None else MagicMock(name="db")
    with patch("workflow_steps.common.run_session.object_session", return_value=session):
        yield session


def settle(
    result: Any, device: DeviceContext, *, node_id: str = "n", step_id: str = "s"
) -> tuple[DeviceContext, bool]:
    """What a per-device work function returned, as ``(device, ok)``.

    A ``Fail`` becomes the failed device the runner would record (its own ``device`` when it
    carries one), so a test can look at ``errors[-1]`` without running the whole step.
    """
    from workflow_steps.common.device_outcomes import mark_device_failed
    from workflow_steps.common.device_runner import Fail

    if isinstance(result, Fail):
        failed = mark_device_failed(
            result.device or device,
            node_id=node_id,
            step_id=step_id,
            code=result.code,
            message=result.message,
            failure=result.failure,
        )
        return failed, False
    return result, True


def strict_xfail(finding: str, why: str) -> pytest.MarkDecorator:
    """Mark a test that documents a known defect; ``finding`` is the W-report id (guard 12)."""
    return pytest.mark.xfail(strict=True, reason=f"{finding}: {why}")


class FakeNautobotGraphQL:
    """The GraphQL side of a Nautobot source with the given devices (``id``, ``name``,
    optional ``primary_ip4`` without mask). Unknown queries fail loudly; every call must be
    ``strict`` like the real resolver's."""

    def __init__(self, devices: Iterable[dict[str, str]]) -> None:
        self.devices = list(devices)
        self.queries: list[str] = []

    async def graphql_query(
        self, query: str, variables: dict[str, Any], credentials: Any, *, strict: bool = False
    ) -> dict[str, Any]:
        assert strict, "the device resolver always queries strictly"
        if "devices(name__ie:" in query:
            self.queries.append("name__ie")
            wanted = {name.casefold() for name in variables["names"]}
            found = [d for d in self.devices if d["name"].casefold() in wanted]
            return {"data": {"devices": [_id_and_name(d) for d in found]}}
        if "devices(name:" in query:
            self.queries.append("name")
            found = [d for d in self.devices if d["name"] in variables["names"]]
            return {"data": {"devices": [_id_and_name(d) for d in found]}}
        if "primary_ip4_for" in query:
            self.queries.append("primary_ip4")
            (address,) = variables["address"]
            owners = [_id_and_name(d) for d in self.devices if d.get("primary_ip4") == address]
            return {"data": {"ip_addresses": [{"address": address, "primary_ip4_for": owners}]}}
        raise AssertionError(f"unexpected query: {query[:60]!r}")


def _id_and_name(device: dict[str, str]) -> dict[str, str]:
    return {"id": device["id"], "name": device["name"]}

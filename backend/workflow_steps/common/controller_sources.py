"""The controller kit: what differs between the Cisco ACI and Catalyst Center steps (W2-03, W8-06).

Both families group devices by ``source_id``, resolve one credential set per source before any
I/O, read facts through a source-agnostic driver (``fact_entries``) and classify a controller
failure by one exception class. ``ControllerSource`` names the few things that differ; ``ACI`` and
``CATALYST_CENTER`` are the two instances. A step calls ``ACI.fact(...)``,
``ACI.run_fact_step(...)`` or, for a hand-written per-device loop,
``CATALYST_CENTER.prepare_targets(...)``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.aci.common.exceptions import AciError, AciValidationError
from services.catalyst_center.common.exceptions import (
    CatalystCenterError,
    CatalystCenterValidationError,
)
from workflow_steps.common.device_outcomes import TargetSplit, failed_device
from workflow_steps.common.fact_entries import (
    Entry,
    FactError,
    collect_facts,
    error_entry,
    ok_entry,
)
from workflow_steps.common.failure_records import INVALID_INPUT
from workflow_steps.common.run_session import require_session
from workflow_steps.common.source_credentials import resolve_source

ACI_SOURCE = "aci"
CATALYST_CENTER_SOURCE = "catalyst_center"
ACI_ERROR_CODE = "aci_error"
CATALYST_ERROR_CODE = "catalyst_center_error"

# (credentials, per-source state from ``prepare``, device id, device) -> entries by fact name
CollectFn = Callable[[Any, Any, str, DeviceContext], Awaitable[dict[str, Entry]]]
PrepareFn = Callable[[Any], Awaitable[Any]]
# A device the step cannot address although it came from the right source: (code, message).
DeviceCheck = Callable[[str, DeviceContext], tuple[str, str] | None]


@dataclass(frozen=True)
class PreparedTargets:
    """The database session, the devices grouped by source and one credential set per source."""

    db: Session
    split: TargetSplit
    credentials: dict[str, Any]


@dataclass(frozen=True)
class ControllerSource:
    source: str  # ``DeviceContext.source`` of a device that came from this controller
    label: str  # "Cisco ACI", "Catalyst Center": names the controller in a message
    error_cls: type[Exception]  # a controller failure; carries ``.failure``
    error_code: str
    validation_error: type[Exception]
    build_source_config: Callable[[Session], Any]
    wrong_source_code: str
    check_device: DeviceCheck | None = None

    def split_targets(
        self, devices: dict[str, DeviceContext], *, step_id: str, node_id: str
    ) -> TargetSplit:
        """Group the controller's devices by source; reject any other device."""
        by_source: dict[str, dict[str, DeviceContext]] = {}
        rejected: dict[str, DeviceContext] = {}
        for device_id, device in devices.items():
            problem: tuple[str, str] | None = None
            if device.source != self.source or not device.source_id:
                problem = (
                    self.wrong_source_code,
                    f"Device {device_id} did not come from a {self.label} source "
                    f"(source={device.source or 'unknown'})",
                )
            elif self.check_device is not None:
                problem = self.check_device(device_id, device)
            if problem is None:
                by_source.setdefault(device.source_id or "", {})[device_id] = device
                continue
            code, message = problem
            rejected[device_id] = failed_device(
                device,
                step_id=step_id,
                node_id=node_id,
                code=code,
                failure=INVALID_INPUT,
                message=message,
            )
        return TargetSplit(by_source=by_source, rejected=rejected)

    def resolve_credentials(self, db: Session, source_id: str, *, step_id: str) -> Any:
        """Credentials of one source; a bad source is a configuration error (ValueError)."""
        return resolve_source(
            self.build_source_config(db), source_id, step_id=step_id, invalid=self.validation_error
        )

    def resolve_all_credentials(
        self, db: Session, source_ids: list[str], *, step_id: str
    ) -> dict[str, Any]:
        source_config = self.build_source_config(db)
        return {
            source_id: resolve_source(
                source_config, source_id, step_id=step_id, invalid=self.validation_error
            )
            for source_id in source_ids
        }

    def prepare_targets(
        self, context: WorkflowContext, run: WorkflowRun, *, step_id: str, node_id: str
    ) -> PreparedTargets:
        """Session, split and per-source credentials: the preamble of every per-device step."""
        db = require_session(run, step_id)
        split = self.split_targets(context.devices, step_id=step_id, node_id=node_id)
        credentials = self.resolve_all_credentials(db, list(split.by_source), step_id=step_id)
        return PreparedTargets(db=db, split=split, credentials=credentials)

    async def capture[T](
        self, fetch: Callable[[], Awaitable[T]]
    ) -> tuple[T | None, FactError | None]:
        """Run one controller read; a controller failure becomes an error with its cause."""
        try:
            return await fetch(), None
        except self.error_cls as exc:
            return None, FactError(str(exc), getattr(exc, "failure", None))

    async def fact(self, fetch: Callable[[], Awaitable[Any]]) -> Entry:
        value, error = await self.capture(fetch)
        return error_entry(error) if error is not None else ok_entry(value)

    async def run_fact_step(
        self,
        *,
        step_id: str,
        context: WorkflowContext,
        run: WorkflowRun,
        node_id: str,
        output_key: str,
        collect: CollectFn,
        prepare: PrepareFn | None = None,
    ) -> list[StepOutcome]:
        """Resolve targets/credentials, collect facts per device, and build the outcomes."""
        if not context.devices:
            return [StepOutcome(name="success", context=context)]
        prepared = self.prepare_targets(context, run, step_id=step_id, node_id=node_id)
        return await collect_facts(
            step_id=step_id,
            context=context,
            node_id=node_id,
            output_key=output_key,
            collect=collect,
            split=prepared.split,
            credentials=prepared.credentials,
            error_code=self.error_code,
            prepare=prepare,
        )


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def aci_node_of(device: DeviceContext) -> tuple[int, int] | None:
    """``(pod_id, node_id)`` of an ACI device, or ``None`` when its bag does not carry both."""
    bag = device.attribute_bags.get(ACI_SOURCE)
    if not isinstance(bag, dict):
        return None
    pod_id, node_id = _positive_int(bag.get("pod_id")), _positive_int(bag.get("node_id"))
    if pod_id is None or node_id is None:
        return None
    return pod_id, node_id


def _check_aci_node(device_id: str, device: DeviceContext) -> tuple[str, str] | None:
    if aci_node_of(device) is not None:
        return None
    return (
        "aci_node_unknown",
        f"Device {device_id} carries no ACI node and pod id; use Get from ACI first",
    )


ACI = ControllerSource(
    source=ACI_SOURCE,
    label="Cisco ACI",
    error_cls=AciError,
    error_code=ACI_ERROR_CODE,
    validation_error=AciValidationError,
    build_source_config=lambda db: service_factory.build_aci_source_config_service(db),
    wrong_source_code="not_aci_device",
    check_device=_check_aci_node,
)

CATALYST_CENTER = ControllerSource(
    source=CATALYST_CENTER_SOURCE,
    label="Catalyst Center",
    error_cls=CatalystCenterError,
    error_code=CATALYST_ERROR_CODE,
    validation_error=CatalystCenterValidationError,
    build_source_config=lambda db: service_factory.build_catalyst_center_source_config_service(db),
    wrong_source_code="not_catalyst_center_device",
)

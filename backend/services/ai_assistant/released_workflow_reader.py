"""DB-backed access to the workflows released for Ask the Net (doc/AI_TOOL_CHAIN.md §16).

Everything runs as the calling user: the workflow must be released *and still the version that was
released* (``release_is_current``: the workflow, the workflows it starts and the release settings
are unchanged), visible to them, and they need ``workflows:execute``. Each call opens its own
short-lived session in a worker thread, like ``DbRunReader``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from core.config import settings
from core.database import SessionLocal
from core.models.workflows import Workflow
from core.safe_hosts import validate_netmiko_preview_host
from repositories.workflow_repository import WorkflowRepository
from services.ai_assistant.device_access import DbDeviceResolver, DeviceAccessError
from services.ai_assistant.released_run_builder import (
    ProposedDevice,
    ReleasedRunError,
    build_run_inputs,
)
from services.ai_assistant.token_once import claim, confirm
from services.ai_assistant.token_once import release as release_claim
from services.ai_assistant.workflow_run_token import InvalidRunTokenError
from services.auth.rbac_service import RBACService
from services.execution.run_service import AiReleaseNotCurrentError, RunService
from services.workflow.device_lines import parse_ipv4_literal
from services.workflow.release_stamp import release_is_current

_CHANGED_SINCE_PROPOSED = (
    "This workflow was changed or released again after it was proposed. Ask the assistant again."
)


class ReleasedWorkflowAccessError(Exception):
    """Not released, not visible, not allowed or changed since: one error, one HTTP code."""

    def __init__(self, message: str = "That workflow is not released for you") -> None:
        super().__init__(message)


class FreeAddressError(DeviceAccessError):
    """An address outside the inventory that this workflow or this server does not accept."""


@dataclass(frozen=True)
class ReleasedWorkflow:
    id: int
    name: str
    description: str
    result_node_id: str | None
    static_attributes: tuple[dict[str, Any], ...]
    devices_input: str | None = None
    credential_inputs: tuple[str, ...] = ()
    allow_free_ip: bool = False
    # The release this view was read from; a proposal carries it and the start must match it.
    release_stamp: str = ""


class ReleasedWorkflowReader(Protocol):
    async def list_released(self) -> list[ReleasedWorkflow]: ...

    async def get_released(self, workflow_id: int) -> ReleasedWorkflow: ...

    async def resolve_devices(
        self, refs: Sequence[str], *, allow_free_ip: bool
    ) -> list[ProposedDevice]: ...

    async def start(
        self,
        workflow_id: int,
        *,
        model_inputs: Mapping[str, Any],
        devices: Sequence[ProposedDevice],
        credentials: Mapping[str, str],
        free_ip_driver: str | None,
        release_stamp: str,
        token_id: str,
    ) -> int: ...


def _to_released(workflow: Workflow) -> ReleasedWorkflow:
    return ReleasedWorkflow(
        id=workflow.id,
        name=workflow.name,
        description=workflow.ai_description or "",
        result_node_id=workflow.ai_result_node_id,
        static_attributes=tuple(workflow.static_attributes or ()),
        devices_input=workflow.ai_devices_input,
        credential_inputs=tuple(workflow.ai_credential_inputs or ()),
        allow_free_ip=bool(workflow.ai_allow_free_ip),
        release_stamp=workflow.ai_release_stamp or "",
    )


def _loader(db: Any) -> Callable[[int], Workflow | None]:
    def load(workflow_id: int) -> Workflow | None:
        found = WorkflowRepository(db).get_by_id(workflow_id)
        return None if found is None else found[0]

    return load


def _visible(workflow: Workflow, user_id: int, db: Any) -> bool:
    """Released, still the version that was released, and visible to the user."""
    return release_is_current(workflow, _loader(db)) and (
        workflow.visibility != "private" or workflow.creator_id == user_id
    )


def free_address(ref: str) -> ProposedDevice:
    """A device for a bare IPv4 address, after the host policy and the typed-host switch."""
    ip = parse_ipv4_literal(ref)
    if ip is None:
        raise FreeAddressError("That is not a single IPv4 address")
    try:
        validate_netmiko_preview_host(
            ip,
            environment=settings.environment,
            allow_arbitrary=settings.allow_netmiko_arbitrary_hosts,
        )
    except ValueError as exc:
        raise FreeAddressError(str(exc)) from exc
    return ProposedDevice(ip=ip, in_inventory=False)


class DbReleasedWorkflowReader:
    def __init__(self, user_id: int) -> None:
        self._user_id = user_id

    async def list_released(self) -> list[ReleasedWorkflow]:
        return await asyncio.to_thread(self._list_released)

    async def get_released(self, workflow_id: int) -> ReleasedWorkflow:
        return await asyncio.to_thread(self._get_released, workflow_id)

    async def resolve_devices(
        self, refs: Sequence[str], *, allow_free_ip: bool
    ) -> list[ProposedDevice]:
        """Inventory devices by exact name, and bare IPv4 addresses.

        An address that is the management address of exactly one inventory device is that device
        (name, platform and driver from the inventory). Only an address the inventory does not know
        is a free address, and only when the release allows it. Both need ``sources.nautobot:read``.

        Raises ``DeviceAccessError`` (a message safe for the model and the user). Two entries that
        end up at the same address are one device.
        """
        resolver = DbDeviceResolver(self._user_id)
        found: dict[str, ProposedDevice] = {}
        for ref in refs:
            ip = parse_ipv4_literal(ref)
            if ip is not None:
                known = await resolver.resolve_by_ip(ip)
                if known is not None:
                    device = ProposedDevice(
                        ip=known.host,
                        name=known.name,
                        network_driver=known.network_driver,
                        platform=known.platform,
                    )
                elif allow_free_ip:
                    device = free_address(ref)
                else:
                    raise FreeAddressError(
                        f"{ref} is an address, not an inventory device name. This workflow only "
                        "accepts devices from the inventory."
                    )
            else:
                resolved = await resolver.resolve(ref)
                device = ProposedDevice(
                    ip=resolved.host,
                    name=resolved.name,
                    network_driver=resolved.network_driver,
                    platform=resolved.platform,
                )
            found.setdefault(device.ip, device)
        return list(found.values())

    async def start(
        self,
        workflow_id: int,
        *,
        model_inputs: Mapping[str, Any],
        devices: Sequence[ProposedDevice],
        credentials: Mapping[str, str],
        free_ip_driver: str | None,
        release_stamp: str,
        token_id: str,
    ) -> int:
        await self._reverify(devices)
        return await asyncio.to_thread(
            self._start,
            workflow_id,
            model_inputs,
            devices,
            credentials,
            free_ip_driver,
            release_stamp,
            token_id,
        )

    async def _reverify(self, devices: Sequence[ProposedDevice]) -> None:
        """The devices as they are now, not as they were when the card was made.

        An inventory device must still resolve to the same address and platform for this user; an
        address outside the inventory must still pass the host policy and the operator switch.
        """
        resolver = DbDeviceResolver(self._user_id)
        try:
            for device in devices:
                if not device.in_inventory:
                    free_address(device.ip)
                    continue
                now = await resolver.resolve(device.name or "")
                if (now.host, now.platform, now.network_driver) != (
                    device.ip,
                    device.platform,
                    device.network_driver,
                ):
                    raise ReleasedRunError(
                        f"{device.label} changed in the inventory since it was proposed. "
                        "Ask the assistant again."
                    )
        except DeviceAccessError as exc:
            raise ReleasedRunError(str(exc)) from exc

    def _require_execute(self, db: Any) -> None:
        if not RBACService(db).has_permission(self._user_id, "workflows", "execute"):
            raise ReleasedWorkflowAccessError

    def _list_released(self) -> list[ReleasedWorkflow]:
        with SessionLocal() as db:
            self._require_execute(db)
            rows = WorkflowRepository(db).list_accessible(self._user_id)
            return [_to_released(w) for w, _ in rows if _visible(w, self._user_id, db)]

    def _get_released(self, workflow_id: int) -> ReleasedWorkflow:
        with SessionLocal() as db:
            self._require_execute(db)
            found = WorkflowRepository(db).get_by_id(workflow_id)
            if found is None or not _visible(found[0], self._user_id, db):
                raise ReleasedWorkflowAccessError
            return _to_released(found[0])

    def _start(
        self,
        workflow_id: int,
        model_inputs: Mapping[str, Any],
        devices: Sequence[ProposedDevice],
        credentials: Mapping[str, str],
        free_ip_driver: str | None,
        release_stamp: str,
        token_id: str,
    ) -> int:
        with SessionLocal() as db:
            self._require_execute(db)
            found = WorkflowRepository(db).get_by_id(workflow_id)
            if found is None or not _visible(found[0], self._user_id, db):
                raise ReleasedWorkflowAccessError
            release = _to_released(found[0])
            if release.release_stamp != release_stamp:
                raise ReleasedWorkflowAccessError(_CHANGED_SINCE_PROPOSED)
            run_inputs = build_run_inputs(
                devices_input=release.devices_input,
                credential_inputs=release.credential_inputs,
                allow_free_ip=release.allow_free_ip,
                model_inputs=model_inputs,
                devices=devices,
                credentials=credentials,
                free_ip_driver=free_ip_driver,
            )
            # Hold the confirmation while the run starts, so a second POST of the same token starts
            # nothing. It is kept only if the run exists and was dispatched; any refusal (a
            # credential the user cannot use, an engine that is down) frees it, so the same card can
            # be corrected and tried again until it expires. A store that cannot record the claim
            # raises and nothing starts (fails closed).
            if not claim(token_id):
                raise InvalidRunTokenError
            try:
                run = RunService(db).trigger_ai_run(
                    workflow_id,
                    self._user_id,
                    run_inputs=run_inputs,
                    expected_stamp=release_stamp,
                )
            except AiReleaseNotCurrentError as exc:
                release_claim(token_id)
                raise ReleasedWorkflowAccessError(str(exc)) from exc
            except BaseException:
                release_claim(token_id)
                raise
            confirm(token_id)
            return run.id

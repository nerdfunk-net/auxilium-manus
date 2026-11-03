"""DbReleasedWorkflowReader and the session gating of the released-workflow tools."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.users import User
from core.models.workflows import Workflow
from services.ai_assistant import released_workflow_reader as module
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.released_workflow_reader import (
    DbReleasedWorkflowReader,
    ReleasedWorkflowAccessError,
)
from services.ai_assistant.surfaces import build_general_session
from services.auth.rbac_service import RBACService
from services.workflow.release_stamp import compute_stamp, release_settings


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Workflow.metadata.create_all(engine, tables=[User.__table__, Workflow.__table__])
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    session = factory()
    session.add_all(
        [
            Workflow(
                id=1,
                name="released",
                creator_id=1,
                visibility="public",
                ai_released=True,
                ai_description="Compare snapshot",
                ai_result_node_id="cmp",
                static_attributes=[{"name": "f", "type": "string"}],
            ),
            Workflow(id=2, name="plain", creator_id=1, visibility="public", ai_released=False),
            Workflow(id=3, name="mine", creator_id=1, visibility="private", ai_released=True),
        ]
    )
    session.commit()
    for workflow in session.query(Workflow).filter(Workflow.ai_released.is_(True)):
        restamp(session, workflow)
    yield session
    session.close()
    engine.dispose()


def restamp(session, workflow: Workflow) -> str:
    """What releasing the workflow as it is now would store."""
    workflow.ai_release_stamp = compute_stamp(
        workflow, release_settings(workflow), lambda wid: session.get(Workflow, wid)
    )
    session.commit()
    return workflow.ai_release_stamp


def test_lists_only_released_workflows_the_user_may_see(db) -> None:
    other = asyncio.run(DbReleasedWorkflowReader(2).list_released())
    owner = asyncio.run(DbReleasedWorkflowReader(1).list_released())
    assert [w.id for w in other] == [1]
    assert sorted(w.id for w in owner) == [1, 3]
    assert other[0].description == "Compare snapshot" and other[0].result_node_id == "cmp"


@pytest.mark.parametrize("workflow_id", [2, 3, 99])
def test_get_refuses_unreleased_private_or_missing(db, workflow_id: int) -> None:
    with pytest.raises(ReleasedWorkflowAccessError):
        asyncio.run(DbReleasedWorkflowReader(2).get_released(workflow_id))


def test_without_execute_permission_nothing_is_available(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: False)
    reader = DbReleasedWorkflowReader(2)
    with pytest.raises(ReleasedWorkflowAccessError):
        asyncio.run(reader.list_released())
    with pytest.raises(ReleasedWorkflowAccessError):
        asyncio.run(reader.get_released(1))
    with pytest.raises(ReleasedWorkflowAccessError):
        asyncio.run(START_NOTHING(reader, 1))


class _Runs:
    pass


def _names(**kw) -> set[str]:
    session = build_general_session(
        user_id=1,
        reader=object(),
        store=None,
        sharing=SharingPolicy(),
        may_query_batfish=False,
        **kw,
    )
    return {s.name for s in session.toolbox.specs()}


def test_tools_need_both_the_released_reader_and_the_run_reader() -> None:
    wanted = {
        "list_released_workflows",
        "describe_workflow",
        "propose_workflow_run",
        "get_run_result",
    }
    assert wanted <= _names(released_reader=object(), run_reader=_Runs())
    assert not wanted & _names(released_reader=object())
    assert not wanted & _names(run_reader=_Runs())


# -- devices: inventory names and strict IPv4 addresses ----------------------------------------


class _Resolver:
    def __init__(self, user_id: int) -> None:
        pass

    async def resolve(self, name: str):
        from services.ai_assistant.device_access import DeviceNotFoundError, ResolvedDevice

        if name == "ghost":
            raise DeviceNotFoundError
        return ResolvedDevice("src", "id1", name, "10.0.0.1", "ios", None)

    async def resolve_by_ip(self, ip: str):
        from services.ai_assistant.device_access import (
            DeviceAccessDeniedError,
            DeviceAmbiguousError,
            ResolvedDevice,
        )

        if ip == "10.7.7.7":  # a managed device, with the platform the inventory knows
            return ResolvedDevice("src", "id7", "core-sw", ip, "cisco_ios", "cisco_ios")
        if ip == "10.8.8.8":
            raise DeviceAmbiguousError
        if ip == "10.9.9.1":
            raise DeviceAccessDeniedError
        return None


@pytest.fixture
def resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "DbDeviceResolver", _Resolver)
    monkeypatch.setattr(module.settings, "environment", "production")
    monkeypatch.setattr(module.settings, "allow_netmiko_arbitrary_hosts", True)


def _resolve(refs: list[str], *, allow_free_ip: bool = False):
    return asyncio.run(
        DbReleasedWorkflowReader(1).resolve_devices(refs, allow_free_ip=allow_free_ip)
    )


def test_inventory_names_resolve_to_their_inventory_address(resolver) -> None:
    (device,) = _resolve(["sw1"])
    assert (device.name, device.ip, device.in_inventory, device.platform) == (
        "sw1",
        "10.0.0.1",
        True,
        "ios",
    )


def test_an_unknown_inventory_name_is_refused(resolver) -> None:
    from services.ai_assistant.device_access import DeviceNotFoundError

    with pytest.raises(DeviceNotFoundError):
        _resolve(["ghost"])


def test_an_address_needs_the_release_to_allow_it(resolver) -> None:
    from services.ai_assistant.released_workflow_reader import FreeAddressError

    with pytest.raises(FreeAddressError, match="inventory"):
        _resolve(["192.168.5.9"])
    (device,) = _resolve(["192.168.5.9"], allow_free_ip=True)
    assert (device.ip, device.name, device.in_inventory) == ("192.168.5.9", None, False)


@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "0.0.0.0", "224.0.0.1"])
def test_addresses_the_host_policy_forbids_are_refused(resolver, address: str) -> None:
    from services.ai_assistant.released_workflow_reader import FreeAddressError

    with pytest.raises(FreeAddressError):
        _resolve([address], allow_free_ip=True)


def test_typed_hosts_need_the_operator_switch_outside_development(
    resolver, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.ai_assistant.released_workflow_reader import FreeAddressError

    monkeypatch.setattr(module.settings, "allow_netmiko_arbitrary_hosts", False)
    with pytest.raises(FreeAddressError):
        _resolve(["192.168.5.9"], allow_free_ip=True)
    monkeypatch.setattr(module.settings, "environment", "development")
    assert _resolve(["192.168.5.9"], allow_free_ip=True)[0].ip == "192.168.5.9"


def test_the_same_address_twice_is_one_device(resolver) -> None:
    assert len(_resolve(["sw1", "sw1"])) == 1


# -- a release counts only while it is unchanged ----------------------------------------------


def test_editing_the_workflow_after_the_release_hides_it(db) -> None:
    wf = db.get(Workflow, 1)
    wf.canvas_nodes = [{"id": "edited"}]
    db.commit()  # the flag is still true: a save that raced the release

    assert asyncio.run(DbReleasedWorkflowReader(2).list_released()) == []
    with pytest.raises(ReleasedWorkflowAccessError):
        asyncio.run(DbReleasedWorkflowReader(2).get_released(1))


def test_editing_a_workflow_it_starts_hides_the_parent(db) -> None:
    child = Workflow(id=10, name="child", creator_id=1, visibility="public")
    db.add(child)
    db.commit()
    parent = db.get(Workflow, 1)
    parent.canvas_nodes = [
        {"id": "s", "data": {"kind": "start-workflow", "pluginConfig": {"workflow_id": 10}}}
    ]
    restamp(db, parent)
    assert [w.id for w in asyncio.run(DbReleasedWorkflowReader(2).list_released())] == [1]

    child.canvas_nodes = [{"id": "changed"}]
    db.commit()
    assert asyncio.run(DbReleasedWorkflowReader(2).list_released()) == []


# -- start: the inputs are built from the release, not from the caller ---------------------


def START_NOTHING(reader, workflow_id: int, **kw):
    args = {
        "model_inputs": {},
        "devices": [],
        "credentials": {},
        "free_ip_driver": None,
        "release_stamp": "x",
        "token_id": "t",
    }
    return reader.start(workflow_id, **{**args, **kw})


@pytest.fixture
def started(db, monkeypatch: pytest.MonkeyPatch):
    """A released workflow 1 with a devices input and a credential input, and a fake run service."""
    from unittest.mock import MagicMock

    wf = db.get(Workflow, 1)
    wf.ai_devices_input = "devs"
    wf.ai_credential_inputs = ["cred"]
    stamp = restamp(db, wf)
    run_service = MagicMock()
    run_service.return_value.trigger_ai_run.return_value = MagicMock(id=99)
    monkeypatch.setattr(module, "RunService", run_service)
    monkeypatch.setattr(module, "DbDeviceResolver", _Resolver)
    used: list[str] = []
    released: list[str] = []
    monkeypatch.setattr(module, "claim", lambda token_id: True)
    monkeypatch.setattr(module, "confirm", used.append)
    monkeypatch.setattr(module, "release_claim", released.append)
    return SimpleNamespace(
        stamp=stamp, service=run_service.return_value, used=used, released=released, db=db
    )


def _start(started, **kw):
    from services.ai_assistant.released_run_builder import ProposedDevice

    args = {
        "model_inputs": {"f": "ospf"},
        "devices": [ProposedDevice(ip="10.0.0.1", name="sw1", platform="ios")],
        "credentials": {"cred": "lab-ssh"},
        "free_ip_driver": None,
        "release_stamp": started.stamp,
        "token_id": "tok-1",
    }
    return asyncio.run(DbReleasedWorkflowReader(2).start(1, **{**args, **kw}))


def test_start_builds_the_run_inputs_and_starts_as_the_user(started) -> None:
    assert _start(started) == 99
    started.service.trigger_ai_run.assert_called_once_with(
        1,
        2,
        run_inputs={"f": "ospf", "cred": "lab-ssh", "devs": "sw1,10.0.0.1,cisco_ios"},
        expected_stamp=started.stamp,
    )
    assert started.used == ["tok-1"]


def test_a_confirmation_works_once(started, monkeypatch: pytest.MonkeyPatch) -> None:
    from services.ai_assistant.workflow_run_token import InvalidRunTokenError

    seen: set[str] = set()
    monkeypatch.setattr(
        module, "claim", lambda token_id: token_id not in seen and not seen.add(token_id)
    )

    assert _start(started) == 99
    with pytest.raises(InvalidRunTokenError):
        _start(started)
    assert started.service.trigger_ai_run.call_count == 1


def test_a_request_that_fails_validation_does_not_use_up_the_confirmation(started) -> None:
    from services.ai_assistant.released_run_builder import ReleasedRunError

    with pytest.raises(ReleasedRunError):
        _start(started, credentials={})
    assert started.used == []


def test_a_proposal_from_before_a_re_release_is_refused(started) -> None:
    wf = started.db.get(Workflow, 1)
    wf.ai_description = "released again"
    restamp(started.db, wf)

    with pytest.raises(ReleasedWorkflowAccessError, match="Ask the assistant again"):
        _start(started)
    started.service.trigger_ai_run.assert_not_called()
    assert started.used == []


def test_a_workflow_edited_since_is_refused(started) -> None:
    wf = started.db.get(Workflow, 1)
    wf.canvas_nodes = [{"id": "edited"}]
    started.db.commit()

    with pytest.raises(ReleasedWorkflowAccessError):
        _start(started)
    started.service.trigger_ai_run.assert_not_called()


def test_the_service_saying_the_release_is_gone_is_the_same_error(started) -> None:
    from services.execution.run_service import AiReleaseNotCurrentError

    started.service.trigger_ai_run.side_effect = AiReleaseNotCurrentError("gone")
    with pytest.raises(ReleasedWorkflowAccessError, match="gone"):
        _start(started)


def test_start_refuses_a_credential_input_the_release_does_not_declare(started) -> None:
    from services.ai_assistant.released_run_builder import ReleasedRunError

    with pytest.raises(ReleasedRunError):
        _start(started, credentials={"cred": "a", "other": "someone-elses"})


def test_start_refuses_a_workflow_that_is_no_longer_released(db) -> None:
    with pytest.raises(ReleasedWorkflowAccessError):
        asyncio.run(START_NOTHING(DbReleasedWorkflowReader(2), 2))


# -- devices are checked again at confirm ---------------------------------------------------


def test_an_inventory_device_whose_address_changed_is_refused(started) -> None:
    from services.ai_assistant.released_run_builder import ProposedDevice, ReleasedRunError

    moved = ProposedDevice(ip="10.9.9.9", name="sw1", platform="ios")  # the resolver says 10.0.0.1
    with pytest.raises(ReleasedRunError, match="changed in the inventory"):
        _start(started, devices=[moved])
    started.service.trigger_ai_run.assert_not_called()
    assert started.used == []


def test_a_device_that_left_the_inventory_is_refused(started) -> None:
    from services.ai_assistant.released_run_builder import ProposedDevice, ReleasedRunError

    with pytest.raises(ReleasedRunError):
        _start(started, devices=[ProposedDevice(ip="10.0.0.1", name="ghost")])


def test_a_free_address_must_still_pass_the_host_policy_and_the_switch(
    started, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.ai_assistant.released_run_builder import ProposedDevice, ReleasedRunError

    wf = started.db.get(Workflow, 1)
    wf.ai_allow_free_ip = True
    stamp = restamp(started.db, wf)
    monkeypatch.setattr(module.settings, "environment", "production")
    monkeypatch.setattr(module.settings, "allow_netmiko_arbitrary_hosts", True)
    free = ProposedDevice(ip="192.168.5.9", in_inventory=False)

    assert _start(started, devices=[free], release_stamp=stamp) == 99

    # the operator switched typed hosts off after the card was made
    monkeypatch.setattr(module.settings, "allow_netmiko_arbitrary_hosts", False)
    with pytest.raises(ReleasedRunError):
        _start(started, devices=[free], release_stamp=stamp, token_id="tok-2")


def test_a_refused_start_frees_the_confirmation_for_a_retry(started) -> None:
    from services.execution.run_service import ValidationFailedError

    started.service.trigger_ai_run.side_effect = ValidationFailedError("credential expired")
    with pytest.raises(ValidationFailedError):
        _start(started)
    assert started.released == ["tok-1"]
    assert started.used == []


def test_a_failed_dispatch_frees_the_confirmation(started) -> None:
    started.service.trigger_ai_run.side_effect = RuntimeError("engine down")
    with pytest.raises(RuntimeError):
        _start(started)
    assert started.released == ["tok-1"]
    assert started.used == []


def test_a_started_run_keeps_the_confirmation(started) -> None:
    assert _start(started) == 99
    assert started.used == ["tok-1"]
    assert started.released == []


def test_an_address_that_is_a_managed_device_is_that_device(resolver) -> None:
    (device,) = _resolve(["10.7.7.7"], allow_free_ip=True)
    assert device.in_inventory is True
    assert (device.name, device.platform, device.network_driver) == (
        "core-sw",
        "cisco_ios",
        "cisco_ios",
    )


def test_a_managed_address_resolves_even_when_free_addresses_are_not_allowed(resolver) -> None:
    (device,) = _resolve(["10.7.7.7"], allow_free_ip=False)
    assert device.in_inventory is True


def test_an_address_shared_by_two_devices_is_ambiguous(resolver) -> None:
    from services.ai_assistant.device_access import DeviceAmbiguousError

    with pytest.raises(DeviceAmbiguousError):
        _resolve(["10.8.8.8"], allow_free_ip=True)


def test_a_free_address_still_needs_inventory_read_permission(resolver) -> None:
    from services.ai_assistant.device_access import DeviceAccessDeniedError

    with pytest.raises(DeviceAccessDeniedError):
        _resolve(["10.9.9.1"], allow_free_ip=True)

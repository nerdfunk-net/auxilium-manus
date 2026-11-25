"""The controller kit: ControllerSource and its ACI and Catalyst Center instances (W2-03, W8-06)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from models.failure import FailureInfo
from models.workflow_context import DeviceContext, DeviceStatus
from services.aci.common.exceptions import AciError, AciValidationError
from services.catalyst_center.common.exceptions import (
    CatalystCenterError,
    CatalystCenterValidationError,
)
from services.settings.source_config_base import SourceNotFoundError
from tests.unit._step_helpers import make_context, make_device, make_run, patch_object_session
from workflow_steps.common.controller_sources import (
    ACI,
    ACI_ERROR_CODE,
    CATALYST_CENTER,
    CATALYST_ERROR_CODE,
    aci_node_of,
)
from workflow_steps.common.fact_entries import error_entry
from workflow_steps.common.failure_records import INVALID_INPUT

BUILDERS = {
    "aci": "service_factory.build_aci_source_config_service",
    "catalyst_center": "service_factory.build_catalyst_center_source_config_service",
}


def _aci(device_id: str, *, source_id: str = "s1", bag: Any = None) -> DeviceContext:
    bags = {} if bag is None else {"aci": bag}
    return make_device(device_id, source="aci", source_id=source_id, attribute_bags=bags)


def test_instances_name_their_codes_classes_and_sources() -> None:
    assert (ACI.source, ACI.error_code, ACI.error_cls) == ("aci", "aci_error", AciError)
    assert (ACI.label, ACI.validation_error) == ("Cisco ACI", AciValidationError)
    assert ACI_ERROR_CODE == ACI.error_code
    assert CATALYST_CENTER.source == "catalyst_center"
    assert (CATALYST_CENTER.error_code, CATALYST_ERROR_CODE) == ("catalyst_center_error",) * 2
    assert CATALYST_CENTER.error_cls is CatalystCenterError
    assert (CATALYST_CENTER.label, CATALYST_CENTER.validation_error) == (
        "Catalyst Center",
        CatalystCenterValidationError,
    )


def test_aci_node_of_needs_two_positive_ints() -> None:
    assert aci_node_of(_aci("a", bag={"pod_id": 1, "node_id": 101})) == (1, 101)
    for bag in (
        {"pod_id": 1},
        {"pod_id": 0, "node_id": 5},
        {"pod_id": True, "node_id": 5},
        {"pod_id": 1, "node_id": "5"},
    ):
        assert aci_node_of(_aci("a", bag=bag)) is None
    assert aci_node_of(_aci("a")) is None


def test_aci_split_groups_by_source_and_rejects_with_codes() -> None:
    good = _aci("g1", bag={"pod_id": 1, "node_id": 1})
    other_fabric = _aci("g2", source_id="s2", bag={"pod_id": 1, "node_id": 2})
    foreign = make_device("f", source="catalyst_center", source_id="s1")
    no_source_id = _aci("n", source_id="", bag={"pod_id": 1, "node_id": 3})
    no_node = _aci("m")
    devices = {d.id: d for d in (good, other_fabric, foreign, no_source_id, no_node)}

    split = ACI.split_targets(devices, step_id="get-aci-details", node_id="n1")

    assert split.by_source == {"s1": {"g1": good}, "s2": {"g2": other_fabric}}
    assert set(split.rejected) == {"f", "n", "m"}
    errors = {k: v.errors[-1] for k, v in split.rejected.items()}
    assert all(v.status is DeviceStatus.FAILED for v in split.rejected.values())
    assert {k: e.code for k, e in errors.items()} == {
        "f": "not_aci_device",
        "n": "not_aci_device",
        "m": "aci_node_unknown",
    }
    assert errors["f"].message == (
        "Device f did not come from a Cisco ACI source (source=catalyst_center)"
    )
    assert errors["n"].message == "Device n did not come from a Cisco ACI source (source=aci)"
    assert errors["m"].message == (
        "Device m carries no ACI node and pod id; use Get from ACI first"
    )
    assert all(
        (e.step_id, e.node_id, e.failure) == ("get-aci-details", "n1", INVALID_INPUT)
        for e in errors.values()
    )


def test_catalyst_split_has_no_node_check() -> None:
    plain = make_device("c1", source="catalyst_center", source_id="cc")
    unknown = make_device("u")
    split = CATALYST_CENTER.split_targets(
        {"c1": plain, "u": unknown}, step_id="get-catalyst-center-health", node_id="n"
    )
    assert split.by_source == {"cc": {"c1": plain}}
    error = split.rejected["u"].errors[-1]
    assert error.code == "not_catalyst_center_device"
    assert error.message == "Device u did not come from a Catalyst Center source (source=unknown)"


@pytest.mark.parametrize("source", [ACI, CATALYST_CENTER], ids=["aci", "catalyst"])
def test_resolve_credentials_turns_config_problems_into_value_errors(source: Any) -> None:
    config = MagicMock()
    config.resolve_credentials.return_value = "creds"
    db = object()
    with patch(BUILDERS[source.source], return_value=config) as build:
        assert source.resolve_credentials(db, "s1", step_id="st") == "creds"
        build.assert_called_once_with(db)
        config.resolve_credentials.assert_called_once_with("s1")

        config.resolve_credentials.side_effect = SourceNotFoundError("s1")
        with pytest.raises(ValueError, match="^st: .*s1"):
            source.resolve_credentials(db, "s1", step_id="st")

        config.resolve_credentials.side_effect = source.validation_error("incomplete")
        with pytest.raises(ValueError, match="^st: incomplete"):
            source.resolve_credentials(db, "s1", step_id="st")

        config.resolve_credentials.side_effect = RuntimeError("db down")
        with pytest.raises(RuntimeError, match="db down"):
            source.resolve_credentials(db, "s1", step_id="st")


def test_prepare_targets_resolves_one_credential_set_per_source() -> None:
    config = MagicMock()
    config.resolve_credentials.side_effect = lambda sid: f"creds-{sid}"
    devices = [
        make_device("a", source="catalyst_center", source_id="s1"),
        make_device("b", source="catalyst_center", source_id="s2"),
        make_device("c", source="catalyst_center", source_id="s1"),
        make_device("x", source="aci", source_id="s9"),
    ]
    with patch_object_session() as db, patch(BUILDERS["catalyst_center"], return_value=config):
        prepared = CATALYST_CENTER.prepare_targets(
            make_context(devices), make_run(), step_id="st", node_id="n"
        )
    assert prepared.db is db
    assert prepared.credentials == {"s1": "creds-s1", "s2": "creds-s2"}
    assert set(prepared.split.rejected) == {"x"}
    assert config.resolve_credentials.call_count == 2  # once per source, not per device


def test_prepare_targets_without_a_session_is_a_bug_not_a_user_error() -> None:
    with (
        patch_object_session(db=None),
        patch("workflow_steps.common.run_session.object_session", return_value=None),
        pytest.raises(RuntimeError, match="^st: WorkflowRun has no active DB session"),
    ):
        ACI.prepare_targets(make_context([_aci("a")]), make_run(), step_id="st", node_id="n")


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [ACI, CATALYST_CENTER], ids=["aci", "catalyst"])
async def test_capture_classifies_only_the_controllers_own_errors(source: Any) -> None:
    info = FailureInfo(phase="api", kind="timeout")

    async def ok() -> int:
        return 7

    async def controller_down() -> int:
        raise source.error_cls("down")

    async def other() -> int:
        raise KeyError("x")

    assert await source.capture(ok) == (7, None)
    with patch.object(source.error_cls, "failure", new_callable=PropertyMock, return_value=info):
        value, error = await source.capture(controller_down)
        assert value is None
        assert (error.message, error.failure) == ("down", info)
        entry = await source.fact(controller_down)
        assert (entry["parsed"], entry["error"], entry["failure"]) == (None, "down", info)
    with pytest.raises(KeyError):
        await source.capture(other)
    assert await source.fact(ok) == {"parsed": 7, "error": None}


@pytest.mark.asyncio
async def test_other_controllers_error_is_not_captured() -> None:
    async def wrong() -> int:
        raise CatalystCenterError("not an apic error")

    with pytest.raises(CatalystCenterError):
        await ACI.capture(wrong)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [ACI, CATALYST_CENTER], ids=["aci", "catalyst"])
async def test_run_fact_step_is_a_noop_without_devices(source: Any) -> None:
    context = make_context()
    outcomes = await source.run_fact_step(
        step_id="st",
        context=context,
        run=make_run(),  # no session: must not be needed
        node_id="n",
        output_key="k",
        collect=MagicMock(),
    )
    assert [(o.name, o.context) for o in outcomes] == [("success", context)]


@pytest.mark.asyncio
async def test_run_fact_step_collects_with_its_own_error_code() -> None:
    config = MagicMock()
    config.resolve_credentials.return_value = "creds"
    seen: list[tuple[Any, str]] = []

    async def collect(creds: Any, state: Any, device_id: str, device: DeviceContext) -> dict:
        seen.append((creds, device_id))
        return {"f": error_entry("x")}

    device = make_device("a", source="catalyst_center", source_id="s1")
    with patch_object_session(), patch(BUILDERS["catalyst_center"], return_value=config):
        outcomes = await CATALYST_CENTER.run_fact_step(
            step_id="st",
            context=make_context([device]),
            run=make_run(),
            node_id="n",
            output_key="k",
            collect=collect,
        )
    assert seen == [("creds", "a")]
    assert [o.name for o in outcomes] == ["success", "failure"]
    failed = outcomes[1].context.devices["a"]
    assert failed.status is DeviceStatus.FAILED
    assert failed.errors[-1].code == CATALYST_ERROR_CODE

"""P-C leftover: ``get-ise-tacacs-key`` and ``update-ise-tacacs-key`` on the per-device runner.

One device that raises something unexpected fails that device only (the class name plus a
``FailureInfo``, never the exception text); a lost ISE connection still stops the run and the
devices already done keep their result.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.workflow_context import DeviceStatus
from services.ise.common.exceptions import ISEAPIError, ISENotFoundError, ISEValidationError
from tests.unit._step_helpers import call_step, make_context, make_device
from workflow_steps.get_ise_tacacs_key import executor as get_mod
from workflow_steps.update_ise_tacacs_key import executor as update_mod

_SECRET = "driver text with 10.9.9.9 and a token"


def _service() -> MagicMock:
    service = MagicMock()
    service.test_connection = AsyncMock(return_value={"total": 0})
    service.get_device = AsyncMock(return_value={"NetworkDevice": {"tacacsSettings": {}}})
    service.update_device = AsyncMock(return_value={"NetworkDevice": {}})
    return service


async def _call(mod: Any, config: dict[str, Any], service: MagicMock, *devices: Any) -> dict:
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=MagicMock()),
        patch("service_factory.build_ise_source_config_service", return_value=MagicMock()),
        patch(f"{mod.__name__}.resolve_source", return_value=MagicMock()),
        patch("service_factory.build_ise_network_device_service", return_value=service),
    ):
        outcomes = await call_step(mod.execute, config, make_context(devices), node_id="n1")
    return {o.name: o.context for o in outcomes}


_UPDATE_CONFIG = {"ise_source_id": "ise", "new_key": "{custom.k}"}
_GET_CONFIG = {
    "ise_source_id": "ise",
    "priority": [
        {"type": t, "enabled": t == "name_any"}
        for t in ("name_exact_32", "name_any", "location_group", "ip_prefix_scan", "ip_range_scan")
    ],
}


def _update_device(name: str) -> Any:
    return make_device(name, attribute_bags={"custom": {"k": "new-key"}})


@pytest.mark.asyncio
async def test_update_unexpected_error_fails_only_that_device() -> None:
    service = _service()

    async def get_device(ise_id: str) -> dict[str, Any]:
        if ise_id == "A":
            raise RuntimeError(_SECRET)
        return {"NetworkDevice": {"tacacsSettings": {}}}

    service.get_device = AsyncMock(side_effect=get_device)
    a = make_device("A", source="ise", attribute_bags={"custom": {"k": "x"}})
    b = make_device("B", source="ise", attribute_bags={"custom": {"k": "x"}})
    result = await _call(update_mod, _UPDATE_CONFIG, service, a, b)

    assert list(result["success"].devices) == ["B"]
    failed = result["failure"].devices["A"]
    assert failed.status is DeviceStatus.FAILED
    error = failed.errors[-1]
    assert error.message == "RuntimeError"
    assert _SECRET not in str(failed.errors)
    assert error.failure is not None
    assert error.failure.kind == "internal_error"
    service.update_device.assert_called_once()


@pytest.mark.asyncio
async def test_update_unexpected_error_while_resolving_fails_only_that_device() -> None:
    service = _service()
    service.get_device_by_name = AsyncMock(
        side_effect=[RuntimeError(_SECRET), {"NetworkDevice": {"id": "ise-b"}}]
    )
    result = await _call(
        update_mod, _UPDATE_CONFIG, service, _update_device("A"), _update_device("B")
    )
    assert list(result["failure"].devices) == ["A"]
    assert list(result["success"].devices) == ["B"]


@pytest.mark.asyncio
async def test_update_lost_connection_keeps_done_devices_and_fails_the_rest() -> None:
    service = _service()
    service.get_device_by_name = AsyncMock(
        side_effect=[{"NetworkDevice": {"id": "ise-a"}}, ISEAPIError("down")]
    )
    result = await _call(
        update_mod,
        _UPDATE_CONFIG,
        service,
        _update_device("A"),
        _update_device("B"),
        _update_device("C"),
    )
    assert list(result["success"].devices) == ["A"]
    assert list(result["failure"].devices) == ["B", "C"]
    assert result["failure"].devices["C"].errors[-1].code == "remote_system_lost"


@pytest.mark.asyncio
async def test_get_unexpected_error_fails_only_that_device_and_hides_text() -> None:
    service = _service()

    async def by_name(name: str) -> dict[str, Any]:
        if name == "A":
            raise RuntimeError(_SECRET)
        if name == "B":
            return {"NetworkDevice": {"name": "B", "tacacsSettings": {"sharedSecret": "k"}}}
        raise ISENotFoundError("none")

    service.get_device_by_name = AsyncMock(side_effect=by_name)
    result = await _call(
        get_mod, _GET_CONFIG, service, make_device("A"), make_device("B"), make_device("C")
    )

    assert list(result["success"].devices) == ["B"]
    assert list(result["failure"].devices) == ["A", "C"]
    error = result["failure"].devices["A"].errors[-1]
    assert error.message == "RuntimeError"
    assert _SECRET not in str(result["failure"].devices["A"].errors)
    assert error.failure is not None
    assert error.failure.kind == "internal_error"
    assert result["failure"].devices["C"].errors[-1].code == "tacacs_key_not_found"
    assert result["failure"].devices["C"].errors[-1].failure.kind == "not_found"


@pytest.mark.asyncio
async def test_get_lost_connection_keeps_done_devices_and_fails_the_rest() -> None:
    service = _service()

    async def by_name(name: str) -> dict[str, Any]:
        if name == "B":
            raise ISEAPIError("down")
        return {"NetworkDevice": {"name": name, "tacacsSettings": {"sharedSecret": "k"}}}

    service.get_device_by_name = AsyncMock(side_effect=by_name)
    result = await _call(
        get_mod, _GET_CONFIG, service, make_device("A"), make_device("B"), make_device("C")
    )
    assert list(result["success"].devices) == ["A"]
    assert list(result["failure"].devices) == ["B", "C"]
    assert result["failure"].devices["B"].errors[-1].code == "remote_system_lost"


@pytest.mark.asyncio
async def test_get_value_error_no_longer_aborts_the_step() -> None:
    service = _service()
    service.get_device_by_name = AsyncMock(
        side_effect=[
            ValueError("bad shape for A"),
            {"NetworkDevice": {"tacacsSettings": {"sharedSecret": "k"}}},
        ]
    )
    result = await _call(get_mod, _GET_CONFIG, service, make_device("A"), make_device("B"))
    assert list(result["success"].devices) == ["B"]
    assert result["failure"].devices["A"].errors[-1].message == "bad shape for A"


@pytest.mark.asyncio
async def test_get_counts_and_key_strategy_survive() -> None:
    service = _service()
    service.get_device_by_name = AsyncMock(
        return_value={"NetworkDevice": {"name": "A", "tacacsSettings": {"sharedSecret": "k"}}}
    )
    present = make_device("P", attribute_bags={"tacacs": {"shared_secret": "have"}})
    result = await _call(get_mod, _GET_CONFIG, service, make_device("A"), present)
    meta = result["success"].metadata
    assert meta["n1.found_count"] == 1
    assert meta["n1.already_present_count"] == 1
    assert meta["n1.not_found_count"] == 0
    assert result["success"].devices["A"].attribute_bags["tacacs"]["key_strategy"] == "name_any"


@pytest.mark.asyncio
async def test_get_lost_connection_carries_the_failure_record() -> None:
    service = _service()
    service.get_device_by_name = AsyncMock(side_effect=ISEAPIError("down", http_status=403))
    result = await _call(get_mod, _GET_CONFIG, service, make_device("A"), make_device("B"))
    for name in ("A", "B"):
        failure = result["failure"].devices[name].errors[-1].failure
        assert failure is not None
        assert failure.kind == "permission_denied"


@pytest.mark.asyncio
async def test_get_failure_outcome_summary_counts_the_misses() -> None:
    service = _service()
    service.get_device_by_name = AsyncMock(side_effect=ISENotFoundError("none"))
    context = make_context([make_device("A"), make_device("B")])
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=MagicMock()),
        patch("service_factory.build_ise_source_config_service", return_value=MagicMock()),
        patch(f"{get_mod.__name__}.resolve_source", return_value=MagicMock()),
        patch("service_factory.build_ise_network_device_service", return_value=service),
    ):
        outcomes = await call_step(get_mod.execute, _GET_CONFIG, context, node_id="n1")
    by_name = {o.name: o for o in outcomes}
    assert by_name["failure"].summary == "no key found for 2 device(s)"
    assert by_name["success"].summary == "found 0, already had key 0, not found 2"


@pytest.mark.asyncio
async def test_update_rejection_carries_the_failure_record_and_summaries() -> None:
    service = _service()
    service.update_device = AsyncMock(side_effect=ISEValidationError("bad", http_status=400))
    a = make_device("A", source="ise", attribute_bags={"custom": {"k": "x"}})
    context = make_context([a])
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=MagicMock()),
        patch("service_factory.build_ise_source_config_service", return_value=MagicMock()),
        patch(f"{update_mod.__name__}.resolve_source", return_value=MagicMock()),
        patch("service_factory.build_ise_network_device_service", return_value=service),
    ):
        outcomes = await call_step(update_mod.execute, _UPDATE_CONFIG, context, node_id="n1")
    by_name = {o.name: o for o in outcomes}
    error = by_name["failure"].context.devices["A"].errors[-1]
    assert error.code == "tacacs_key_update_rejected"
    assert error.failure is not None
    assert error.failure.kind == "bad_request"
    assert by_name["failure"].summary == "1 device(s) not updated"
    assert by_name["success"].summary == "updated 0, failed 1"


@pytest.mark.asyncio
async def test_update_lost_connection_while_resolving_carries_the_failure_record() -> None:
    service = _service()
    service.get_device_by_name = AsyncMock(side_effect=ISEAPIError("down", http_status=403))
    result = await _call(update_mod, _UPDATE_CONFIG, service, _update_device("A"))
    failure = result["failure"].devices["A"].errors[-1].failure
    assert failure is not None
    assert failure.kind == "permission_denied"


@pytest.mark.asyncio
async def test_update_lost_connection_while_updating_carries_the_failure_record() -> None:
    service = _service()
    service.update_device = AsyncMock(side_effect=ISEAPIError("down", http_status=403))
    a = make_device("A", source="ise", attribute_bags={"custom": {"k": "x"}})
    result = await _call(update_mod, _UPDATE_CONFIG, service, a)
    error = result["failure"].devices["A"].errors[-1]
    assert error.code == "remote_system_lost"
    assert error.failure is not None
    assert error.failure.kind == "permission_denied"

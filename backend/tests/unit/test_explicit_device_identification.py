"""W5-02 (D7): ``device_identifier.mode = explicit`` is strict in both Nautobot device steps.

``update-nautobot-device`` (Update Device) used to hand an explicit name to the first-match
service resolver and, with no id or name, wrote to a Nautobot device called "explicit".
Both steps now resolve the explicit device like a context device (strict resolver) and refuse an
identifier with neither ``id``, ``name`` nor ``ip_address`` as a config error.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.workflow_context import DeviceStatus
from tests.unit._step_helpers import call_step, make_context, make_device, patch_object_session
from workflow_steps.common.nautobot_target import (
    explicit_device_context,
    parse_explicit_identifier,
)
from workflow_steps.update_config_context import executor as context_mod
from workflow_steps.update_nautobot_device import executor as device_mod

_UUID = "11111111-1111-1111-1111-111111111111"
_UUID2 = "22222222-2222-2222-2222-222222222222"
_ID_RESULT = {"device_id": _UUID, "device_name": "r1", "interfaces_failed": 0}


def _device_config(identifier: dict[str, Any]) -> dict[str, Any]:
    return {
        "nautobot_source_id": "src-1",
        "device_identifier": {"mode": "explicit", **identifier},
        "update_fields": {"name": {"enabled": True, "value": "new"}},
    }


def _service(*, devices: list[dict[str, str]] | None = None) -> tuple[MagicMock, MagicMock]:
    """(nautobot service answering the name query, update service recording the write)."""
    nautobot = MagicMock()
    nautobot.graphql_query = AsyncMock(return_value={"data": {"devices": devices or []}})
    update_service = MagicMock()
    update_service.update_device = AsyncMock(return_value=_ID_RESULT)
    return nautobot, update_service


async def _run_device(config: dict[str, Any], nautobot: MagicMock, update_service: MagicMock):
    with (
        patch_object_session(device_mod.__name__),
        patch.object(
            device_mod,
            "_build_update_service",
            return_value=(nautobot, MagicMock(), update_service),
        ),
        patch.object(device_mod, "build_resolved_update_data", return_value={"name": "new"}),
    ):
        outcomes = await call_step(device_mod.execute, config, make_context([]))
    return {outcome.name: outcome.context for outcome in outcomes}


class TestParseExplicitIdentifier:
    @pytest.mark.parametrize("raw", [None, {}, {"id": ""}, {"name": "  ", "ip_address": None}, "x"])
    def test_nothing_set_is_a_config_error(self, raw: Any) -> None:
        with pytest.raises(ValueError, match="explicit"):
            parse_explicit_identifier(raw, step_id="s")

    def test_keeps_only_the_set_stripped_keys(self) -> None:
        raw = {"mode": "explicit", "id": " abc ", "name": "", "ip_address": "10.0.0.1"}
        assert parse_explicit_identifier(raw, step_id="s") == {
            "id": "abc",
            "ip_address": "10.0.0.1",
        }

    def test_placeholder_device_carries_the_identifier(self) -> None:
        device = explicit_device_context({"name": "r1", "ip_address": "10.0.0.1"})
        assert (device.id, device.name, device.primary_ip4, device.source) == (
            "explicit",
            "r1",
            "10.0.0.1",
            "nautobot",
        )
        assert explicit_device_context({"id": _UUID}).id == _UUID


@pytest.mark.parametrize("identifier", [{}, {"id": "", "name": " "}])
class TestEmptyIdentifierIsAConfigError:
    def test_update_device(self, identifier: dict[str, Any]) -> None:
        with pytest.raises(ValueError, match="explicit"):
            device_mod._parse_config(_device_config(identifier))

    def test_update_config_context(self, identifier: dict[str, Any]) -> None:
        config = {
            "nautobot_source_id": "src-1",
            "mode": "write",
            "value_source": {"type": "attribute", "attribute_path": "x"},
            "device_identifier": {"mode": "explicit", **identifier},
        }
        with pytest.raises(ValueError, match="explicit"):
            context_mod._parse_config(config)


@pytest.mark.asyncio
class TestUpdateDeviceExplicitMode:
    async def test_empty_identifier_never_looks_up_a_device_called_explicit(self) -> None:
        nautobot, update_service = _service(devices=[{"id": _UUID, "name": "explicit"}])
        with pytest.raises(ValueError, match="explicit"):
            await _run_device(_device_config({}), nautobot, update_service)
        nautobot.graphql_query.assert_not_called()
        update_service.update_device.assert_not_called()

    async def test_two_devices_of_one_name_fail_instead_of_the_first_being_written(self) -> None:
        nautobot, update_service = _service(
            devices=[{"id": _UUID, "name": "r1"}, {"id": _UUID2, "name": "r1"}]
        )
        out = await _run_device(_device_config({"name": "r1"}), nautobot, update_service)
        update_service.update_device.assert_not_called()
        failed = out["failure"].devices["explicit"]
        assert failed.status is DeviceStatus.FAILED
        assert "2 Nautobot devices are named 'r1'" in failed.errors[0].message

    async def test_unknown_name_is_not_found(self) -> None:
        nautobot, update_service = _service(devices=[])
        out = await _run_device(_device_config({"name": "r1"}), nautobot, update_service)
        update_service.update_device.assert_not_called()
        assert out["failure"].devices["explicit"].errors[0].code == "not_found"

    async def test_a_unique_name_is_written_by_its_resolved_id(self) -> None:
        nautobot, update_service = _service(devices=[{"id": _UUID, "name": "r1"}])
        out = await _run_device(_device_config({"name": "r1"}), nautobot, update_service)
        assert list(out["success"].devices) == ["explicit"]
        assert update_service.update_device.call_args.kwargs["device_identifier"] == {"id": _UUID}

    async def test_a_uuid_is_trusted_without_a_lookup(self) -> None:
        nautobot, update_service = _service()
        await _run_device(_device_config({"id": _UUID}), nautobot, update_service)
        nautobot.graphql_query.assert_not_called()
        assert update_service.update_device.call_args.kwargs["device_identifier"] == {"id": _UUID}

    async def test_ip_address_is_accepted_like_update_config_context(self) -> None:
        nautobot, update_service = _service()
        nautobot.graphql_query = AsyncMock(
            return_value={
                "data": {
                    "ip_addresses": [
                        {"address": "10.0.0.1/32", "primary_ip4_for": [{"id": _UUID, "name": "r1"}]}
                    ]
                }
            }
        )
        out = await _run_device(
            _device_config({"ip_address": "10.0.0.1"}), nautobot, update_service
        )
        assert list(out["success"].devices) == ["explicit"]
        assert update_service.update_device.call_args.kwargs["device_identifier"] == {"id": _UUID}

    async def test_context_devices_still_resolve_by_name(self) -> None:
        nautobot, update_service = _service(devices=[{"id": _UUID, "name": "r1"}])
        config = {
            "nautobot_source_id": "src-1",
            "update_fields": {"name": {"enabled": True, "value": "new"}},
        }
        with (
            patch_object_session(device_mod.__name__),
            patch.object(
                device_mod,
                "_build_update_service",
                return_value=(nautobot, MagicMock(), update_service),
            ),
            patch.object(device_mod, "build_resolved_update_data", return_value={"name": "new"}),
        ):
            outcomes = await call_step(
                device_mod.execute, config, make_context([make_device("r1")])
            )
        assert list(outcomes[0].context.devices) == ["r1"]
        assert update_service.update_device.call_args.kwargs["device_identifier"] == {"id": _UUID}


# --- W5-14: a mistyped identifier mode is a config error, not "from_context" -----------------


@pytest.mark.parametrize("bad_mode", ["explicti", "Explicit-ish", "context", "none"])
def test_unknown_identifier_mode_is_a_config_error_in_both_steps(bad_mode: str) -> None:
    device_config = {
        "nautobot_source_id": "src-1",
        "device_identifier": {"mode": bad_mode, "name": "r1"},
        "update_fields": {"name": {"enabled": True, "value": "new"}},
    }
    with pytest.raises(ValueError, match="device_identifier.mode"):
        device_mod._parse_config(device_config)
    with pytest.raises(ValueError, match="device_identifier.mode"):
        context_mod._parse_config(
            {
                "nautobot_source_id": "src-1",
                "device_identifier": {"mode": bad_mode, "name": "r1"},
                "updates": [{"path": "a", "value_source": {"type": "fixed", "value": "1"}}],
            }
        )


def test_missing_or_from_context_mode_still_means_the_context_devices() -> None:
    fields = {"name": {"enabled": True, "value": "x"}}
    base = {"nautobot_source_id": "src-1", "update_fields": fields}
    assert device_mod._parse_config(base).identifier_mode == "from_context"
    assert (
        device_mod._parse_config(
            {**base, "device_identifier": {"mode": " From_Context "}}
        ).identifier_mode
        == "from_context"
    )

"""Resolving a device by inventory name and running confirmed commands on it (§29 steps 3, 5)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.sources_nautobot import DeviceInfo
from services.ai_assistant import device_access as da


def _device(name: str, ip: str | None = "10.1.2.3/24", **extra) -> DeviceInfo:
    return DeviceInfo(
        id=extra.pop("id", f"id-{name}"),
        name=name,
        primary_ip4=ip,
        platform=extra.pop("platform", "cisco_ios"),
        platform_network_driver=extra.pop("driver", "cisco_ios"),
        **extra,
    )


# -- selection (pure) -------------------------------------------------------------------------


def test_one_exact_match_is_resolved_with_the_mask_removed() -> None:
    chosen = da.select_device("LAB", [("nb1", _device("LAB"))])

    assert chosen == da.ResolvedDevice(
        source_id="nb1",
        device_id="id-LAB",
        name="LAB",
        host="10.1.2.3",
        platform="cisco_ios",
        network_driver="cisco_ios",
    )


def test_a_host_without_a_mask_is_kept() -> None:
    assert da.select_device("LAB", [("nb1", _device("LAB", ip="192.0.2.9"))]).host == "192.0.2.9"


def test_no_match_is_not_found_and_substring_matches_do_not_count() -> None:
    with pytest.raises(da.DeviceNotFoundError):
        da.select_device("LAB", [("nb1", _device("LAB-2")), ("nb1", _device("MYLAB"))])
    with pytest.raises(da.DeviceNotFoundError):
        da.select_device("LAB", [])


def test_exact_case_wins_over_a_different_case() -> None:
    chosen = da.select_device(
        "LAB", [("nb1", _device("lab", id="a")), ("nb1", _device("LAB", id="b"))]
    )

    assert chosen.device_id == "b"


def test_a_single_case_insensitive_match_is_accepted() -> None:
    assert da.select_device("lab", [("nb1", _device("LAB"))]).name == "LAB"


def test_two_case_insensitive_matches_are_ambiguous() -> None:
    with pytest.raises(da.DeviceAmbiguousError):
        da.select_device("lab", [("nb1", _device("LAB", id="a")), ("nb1", _device("Lab", id="b"))])


def test_the_same_name_in_two_sources_is_ambiguous() -> None:
    with pytest.raises(da.DeviceAmbiguousError):
        da.select_device("LAB", [("nb1", _device("LAB")), ("nb2", _device("LAB"))])


def test_a_device_without_a_primary_address_cannot_be_reached() -> None:
    with pytest.raises(da.DeviceNoAddressError):
        da.select_device("LAB", [("nb1", _device("LAB", ip=None))])
    with pytest.raises(da.DeviceNoAddressError):
        da.select_device("LAB", [("nb1", _device("LAB", ip="  "))])


@pytest.mark.parametrize("ip", ["127.0.0.1/8", "169.254.169.254/32", "0.0.0.0/0", "not-an-ip/24"])
def test_an_address_the_app_must_never_connect_to_is_refused(ip: str) -> None:
    with pytest.raises(da.DeviceNoAddressError):
        da.select_device("LAB", [("nb1", _device("LAB", ip=ip))])


# -- the database-backed resolver -------------------------------------------------------------


class _Resolver(da.DbDeviceResolver):
    def __init__(self, sources, found) -> None:
        super().__init__(user_id=3)
        self._sources = sources
        self._found = found
        self.searched: list[tuple[str, str]] = []

    def _load_sources(self):
        if self._sources is None:
            raise da.DeviceAccessDeniedError
        return self._sources

    async def _search(self, credentials, name):
        self.searched.append((credentials, name))
        return self._found[credentials]


def test_resolver_searches_every_configured_source_and_selects() -> None:
    resolver = _Resolver(
        [("nb1", "cred1"), ("nb2", "cred2")],
        {"cred1": [_device("LAB-X")], "cred2": [_device("LAB", id="z")]},
    )

    chosen = asyncio.run(resolver.resolve("LAB"))

    assert (chosen.source_id, chosen.device_id) == ("nb2", "z")
    assert [s[1] for s in resolver.searched] == ["LAB", "LAB"]


def test_resolver_without_permission_or_sources_is_a_clear_error() -> None:
    with pytest.raises(da.DeviceAccessDeniedError):
        asyncio.run(_Resolver(None, {}).resolve("LAB"))
    with pytest.raises(da.DeviceNotFoundError):
        asyncio.run(_Resolver([], {}).resolve("LAB"))


# -- running the commands ---------------------------------------------------------------------


def _resolved() -> da.ResolvedDevice:
    return da.ResolvedDevice("nb1", "id-LAB", "LAB", "10.1.2.3", "cisco_ios", "cisco_ios")


def test_runner_sends_the_inventory_host_and_the_users_credential() -> None:
    from models.netmiko import NetmikoCommandEntry, NetmikoRunCommandsResponse

    response = NetmikoRunCommandsResponse(
        success=True,
        commands=[
            NetmikoCommandEntry(node_id="x", name="show version", success=True, raw="IOS 15"),
        ],
    )
    service = MagicMock()
    service.run_commands = AsyncMock(return_value=response)
    with (
        patch.object(da, "SessionLocal"),
        patch.object(da, "CredentialsService"),
        patch.object(da, "NetmikoPreviewService", return_value=service),
    ):
        out = asyncio.run(
            da.DbDeviceCommandRunner().run(
                _resolved(), ["show version"], credential_id=9, user_id=3
            )
        )

    request = service.run_commands.call_args.args[0]
    assert (request.host, request.credential_id, request.commands) == (
        "10.1.2.3",
        9,
        ["show version"],
    )
    assert request.use_textfsm is False
    assert (request.network_driver, request.platform) == ("cisco_ios", "cisco_ios")
    assert service.run_commands.call_args.kwargs == {
        "acting_user_id": 3,
        "host_from_inventory": True,
        "read_timeout": None,
    }
    assert out == da.DeviceCommandOutput(
        success=True, error=None, outputs=(("show version", "IOS 15"),)
    )


def test_runner_reports_a_failed_connection_without_outputs() -> None:
    from models.netmiko import NetmikoRunCommandsResponse

    service = MagicMock()
    service.run_commands = AsyncMock(
        return_value=NetmikoRunCommandsResponse(success=False, commands=[], error="timed out")
    )
    with (
        patch.object(da, "SessionLocal"),
        patch.object(da, "CredentialsService"),
        patch.object(da, "NetmikoPreviewService", return_value=service),
    ):
        out = asyncio.run(
            da.DbDeviceCommandRunner().run(
                _resolved(), ["show version"], credential_id=9, user_id=3
            )
        )

    assert out.success is False
    assert out.error == "timed out"
    assert out.outputs == ()


def _summaries(*ids: str):
    from models.sources_nautobot import NautobotConfiguredSource, NautobotConfiguredSourcesResponse

    return NautobotConfiguredSourcesResponse(
        sources=[
            NautobotConfiguredSource(source_id=i, url=f"https://{i}", token_configured=True)
            for i in ids
        ]
    )


def test_loading_sources_needs_the_nautobot_read_permission() -> None:
    rbac = MagicMock()
    rbac.return_value.has_permission.return_value = False
    settings_service = MagicMock()
    with (
        patch.object(da, "SessionLocal"),
        patch.object(da, "RBACService", rbac),
        patch.object(da, "SettingsService", settings_service),
        pytest.raises(da.DeviceAccessDeniedError),
    ):
        da.DbDeviceResolver(user_id=3)._load_sources()

    rbac.return_value.has_permission.assert_called_once_with(3, "sources.nautobot", "read")
    settings_service.assert_not_called()


def test_loading_sources_skips_an_unusable_source_and_keeps_the_others() -> None:
    def credentials(source_id, db):
        if source_id == "bad":
            raise RuntimeError("no url")
        return f"creds-{source_id}"

    rbac = MagicMock()
    rbac.return_value.has_permission.return_value = True
    settings_service = MagicMock()
    settings_service.return_value.list_nautobot_source_summaries.return_value = _summaries(
        "bad", "good"
    )
    with (
        patch.object(da, "SessionLocal"),
        patch.object(da, "RBACService", rbac),
        patch.object(da, "SettingsService", settings_service),
        patch.object(da, "nautobot_credentials_from_source_id", credentials),
    ):
        loaded = da.DbDeviceResolver(user_id=3)._load_sources()

    assert loaded == [("good", "creds-good")]


# -- device type (the platform / driver the inventory knows) ----------------------------------


@pytest.mark.parametrize(
    ("driver", "platform", "known"),
    [
        ("cisco_ios", None, True),
        (None, "Cisco IOS-XE", True),
        (None, "arista_eos", True),
        ("juniper_junos", "whatever", True),
        (None, None, False),
        ("", "", False),
        ("lab", None, False),
        (None, "Plan 9", False),
    ],
)
def test_driver_known_says_whether_netmiko_can_pick_a_driver(driver, platform, known) -> None:
    device = da.ResolvedDevice("nb1", "id", "LAB", "10.1.2.3", platform, driver)

    assert da.driver_known(device) is known


def test_the_override_choices_are_exactly_the_drivers_the_app_maps() -> None:
    from services.network.netmiko.platform import _PLATFORM_MAP

    assert set(da.DEVICE_DRIVERS) == set(_PLATFORM_MAP.values())


def test_runner_turns_an_unknown_platform_into_a_clear_device_error() -> None:
    from services.network.netmiko.platform import UnsupportedPlatformError

    service = MagicMock()
    service.run_commands = AsyncMock(side_effect=UnsupportedPlatformError(None, None))
    with (
        patch.object(da, "SessionLocal"),
        patch.object(da, "CredentialsService"),
        patch.object(da, "NetmikoPreviewService", return_value=service),
        pytest.raises(da.DeviceUnsupportedPlatformError) as info,
    ):
        asyncio.run(
            da.DbDeviceCommandRunner().run(
                _resolved(), ["show version"], credential_id=9, user_id=3
            )
        )

    assert "device type" in str(info.value).lower()


def test_with_an_override_the_driver_goes_to_netmiko_instead_of_the_inventory_value() -> None:
    from models.netmiko import NetmikoRunCommandsResponse

    service = MagicMock()
    service.run_commands = AsyncMock(
        return_value=NetmikoRunCommandsResponse(success=True, commands=[])
    )
    unknown = da.ResolvedDevice("nb1", "id", "LAB", "10.1.2.3", None, None)
    with (
        patch.object(da, "SessionLocal"),
        patch.object(da, "CredentialsService"),
        patch.object(da, "NetmikoPreviewService", return_value=service),
    ):
        asyncio.run(
            da.DbDeviceCommandRunner().run(
                unknown, ["show version"], credential_id=9, user_id=3, network_driver="cisco_xe"
            )
        )

    assert service.run_commands.call_args.args[0].network_driver == "cisco_xe"


@pytest.mark.parametrize(
    ("commands", "long"),
    [
        (["show running-config"], True),
        (["show startup-config"], True),
        (["show running-config | section ^interface"], True),
        (["show configuration | display set"], True),
        (["show tech-support"], True),
        (["show version", "show startup-config"], True),
        (["show version"], False),
        (["show ip route"], False),
    ],
)
def test_config_dumps_get_the_long_read_timeout_and_other_commands_the_default(
    commands, long
) -> None:
    from models.netmiko import NetmikoRunCommandsResponse
    from services.network.netmiko.connection import DEFAULT_CONFIG_READ_TIMEOUT

    service = MagicMock()
    service.run_commands = AsyncMock(
        return_value=NetmikoRunCommandsResponse(success=True, commands=[])
    )
    with (
        patch.object(da, "SessionLocal"),
        patch.object(da, "CredentialsService"),
        patch.object(da, "NetmikoPreviewService", return_value=service),
    ):
        asyncio.run(
            da.DbDeviceCommandRunner().run(_resolved(), commands, credential_id=9, user_id=3)
        )

    expected = DEFAULT_CONFIG_READ_TIMEOUT if long else None
    assert service.run_commands.call_args.kwargs["read_timeout"] == expected

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
        "interrupt_on_timeout": False,
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


def test_select_device_by_ip_finds_the_one_device() -> None:
    from models.sources_nautobot import DeviceInfo
    from services.ai_assistant.device_access import select_device_by_ip

    device = DeviceInfo(
        id="d1",
        name="core-sw",
        platform="ios",
        platform_network_driver="cisco_ios",
        primary_ip4="10.0.0.5/24",
    )
    found = select_device_by_ip([("src", device)])
    assert found is not None
    assert (found.name, found.host, found.network_driver) == ("core-sw", "10.0.0.5", "cisco_ios")


def test_select_device_by_ip_is_none_without_a_match() -> None:
    from services.ai_assistant.device_access import select_device_by_ip

    assert select_device_by_ip([]) is None


def test_select_device_by_ip_refuses_two_devices_on_one_address() -> None:
    import pytest

    from models.sources_nautobot import DeviceInfo
    from services.ai_assistant.device_access import DeviceAmbiguousError, select_device_by_ip

    a = DeviceInfo(id="a", name="a", primary_ip4="10.0.0.5/24")
    b = DeviceInfo(id="b", name="b", primary_ip4="10.0.0.5/24")
    with pytest.raises(DeviceAmbiguousError):
        select_device_by_ip([("src", a), ("src", b)])


@pytest.mark.parametrize(
    ("commands", "interrupt"),
    [
        (["ping 10.0.0.1 repeat 5"], True),
        (["ping 10.0.0.1 repeat 5", "traceroute 10.0.0.1"], True),
        (["show version"], False),
        (["ping 10.0.0.1 repeat 5", "show version"], False),
    ],
)
def test_only_a_pure_probe_run_is_interrupted_on_timeout(commands, interrupt) -> None:
    from models.netmiko import NetmikoRunCommandsResponse

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
    assert service.run_commands.call_args.kwargs["interrupt_on_timeout"] is interrupt


# -- name or IPv4 address (resolve_device_ref) ------------------------------------------------


class _RefResolver:
    """Records which path ``resolve_device_ref`` took."""

    def __init__(self, by_ip=None, by_name=None, name_error=None) -> None:
        # By default the device's own name finds it again, as in a healthy inventory.
        self.by_ip, self.by_name, self.name_error, self.calls = (
            by_ip,
            by_name or by_ip,
            name_error,
            [],
        )

    async def resolve(self, name):
        self.calls.append(("name", name))
        if self.name_error:
            raise self.name_error
        return self.by_name

    async def resolve_by_ip(self, ip):
        self.calls.append(("ip", ip))
        return self.by_ip


_LAB = da.ResolvedDevice("nb1", "d1", "LAB", "10.1.2.3", "cisco_ios", "cisco_ios")


def test_an_ipv4_address_is_looked_up_by_management_address() -> None:
    resolver = _RefResolver(by_ip=_LAB)

    assert asyncio.run(da.resolve_device_ref(resolver, "10.1.2.3")) is _LAB
    # The name is looked up too: the confirm step finds the device again by it.
    assert resolver.calls == [("ip", "10.1.2.3"), ("name", "LAB")]


def test_a_name_still_goes_through_the_name_lookup() -> None:
    resolver = _RefResolver(by_name=_LAB)

    assert asyncio.run(da.resolve_device_ref(resolver, "LAB")) is _LAB
    assert resolver.calls == [("name", "LAB")]


def test_an_address_that_no_inventory_device_has_is_refused_not_used_as_a_host() -> None:
    resolver = _RefResolver(by_ip=None)

    with pytest.raises(da.DeviceAddressNotFoundError) as caught:
        asyncio.run(da.resolve_device_ref(resolver, "10.9.9.9"))

    assert isinstance(caught.value, da.DeviceNotFoundError)  # the confirm step maps it to 404
    assert "inventory" in str(caught.value)
    assert "10.9.9.9" not in str(caught.value)


@pytest.mark.parametrize("ref", ["10.1.2.3/24", "10.1.2", "300.1.1.1", "01.2.3.4", "lab.example"])
def test_anything_that_is_not_one_ipv4_literal_is_a_name(ref: str) -> None:
    resolver = _RefResolver(by_name=_LAB)

    asyncio.run(da.resolve_device_ref(resolver, ref))

    assert resolver.calls == [("name", ref)]


def test_the_address_lookup_needs_the_same_permission_as_a_name_lookup() -> None:
    resolver = _Resolver(None, {})

    with pytest.raises(da.DeviceAccessDeniedError):
        asyncio.run(da.resolve_device_ref(resolver, "10.1.2.3"))


def test_an_address_whose_device_name_is_shared_gives_no_card_that_could_not_be_run() -> None:
    # The confirm step looks the device up by name; with two devices of that name it would refuse.
    resolver = _RefResolver(by_ip=_LAB, name_error=da.DeviceAmbiguousError())

    with pytest.raises(da.DeviceNameNotUniqueError) as caught:
        asyncio.run(da.resolve_device_ref(resolver, "10.1.2.3"))

    assert isinstance(caught.value, da.DeviceAmbiguousError)  # the confirm step maps it to 409
    assert "name" in str(caught.value) and "address" in str(caught.value)


def test_an_address_whose_name_picks_another_device_is_refused() -> None:
    other = da.ResolvedDevice("nb1", "d2", "LAB", "10.9.9.9", "cisco_ios", "cisco_ios")
    resolver = _RefResolver(by_ip=_LAB, by_name=other)

    with pytest.raises(da.DeviceNameNotUniqueError):
        asyncio.run(da.resolve_device_ref(resolver, "10.1.2.3"))


def test_a_name_that_cannot_be_found_again_is_refused() -> None:
    resolver = _RefResolver(by_ip=_LAB, name_error=da.DeviceNotFoundError())

    with pytest.raises(da.DeviceNameNotUniqueError):
        asyncio.run(da.resolve_device_ref(resolver, "10.1.2.3"))


def test_two_devices_with_one_address_say_address_not_name() -> None:
    found = [("nb1", _device("A", id="a")), ("nb1", _device("B", id="b"))]

    with pytest.raises(da.DeviceAddressAmbiguousError) as caught:
        da.select_device_by_ip(found)

    assert isinstance(caught.value, da.DeviceAmbiguousError)
    assert "address" in str(caught.value)
    assert "that name" not in str(caught.value)

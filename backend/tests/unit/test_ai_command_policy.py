"""The read-only command policy for device commands (doc/AI_TOOL_CHAIN.md §13.2 layer 2)."""

from __future__ import annotations

import pytest

from services.ai_assistant import command_policy as cp


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("show running-config", "show running-config"),
        ("show version", "show version"),
        ("  show   ip   interface   brief  ", "show ip interface brief"),
        ("show\tip route 10.1.2.3", "show ip route 10.1.2.3"),
        ("show running-config | include hostname", "show running-config | include hostname"),
        ("show running-config | section ^interface", "show running-config | section ^interface"),
        ("show ip route | begin 10.0", "show ip route | begin 10.0"),
        ("show interfaces | count", "show interfaces | count"),
        ("show configuration | display set", "show configuration | display set"),
        ("show route | no-more", "show route | no-more"),
        ("show lldp neighbors detail", "show lldp neighbors detail"),
        ("show interface GigabitEthernet0/1", "show interface GigabitEthernet0/1"),
        ("show running-config", "show running-config"),  # "get the running config of LAB"
        ("show startup-config", "show startup-config"),  # "get the startup config of LAB"
    ],
)
def test_read_only_show_commands_are_allowed_and_normalised(raw: str, expected: str) -> None:
    assert cp.check_command(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "conf t",
        "configure terminal",
        "reload",
        "wr",
        "write memory",
        "copy running-config startup-config",
        "erase startup-config",
        "delete flash:config",
        "clear ip bgp *",
        "debug ip packet",
        "terminal length 0",
        "enable",
        "ping 10.0.0.1",
        "traceroute 10.0.0.1",
        "ssh 10.0.0.1",
        "telnet 10.0.0.1",
        "request system reboot",
        "set system host-name x",
        "commit",
        "sh run",
        "sho run",
        "show",
        "showrunning-config",
        "shows version",
    ],
)
def test_anything_that_is_not_a_full_show_command_is_refused(raw: str) -> None:
    with pytest.raises(cp.CommandNotAllowedError):
        cp.check_command(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "show version; reload",
        "show version && reload",
        "show version & reload",
        "show version\nreload",
        "show version\rreload",
        "show version\x00",
        "show version `reload`",
        "show version $(reload)",
        "show version > flash:out",
        "show version >> flash:out",
        "show version < x",
        "show run | redirect flash:out",
        "show run | tee flash:out",
        "show run | append flash:out",
        "show run | save out",
        "show run | file out",
        "show run | include a | include b",
        "show run | include a; reload",
        "show run | include",
        "show run |",
        "show run | display foo",
        "show run | include $(x)",
        "show run | include a\\b",
        "show run || reload",
        "show\\ version",
        "show version #",
    ],
)
def test_chaining_redirection_and_unsafe_pipes_are_refused(raw: str) -> None:
    with pytest.raises(cp.CommandNotAllowedError):
        cp.check_command(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "ѕhow version",  # Cyrillic s
        "show vеrsion",  # Cyrillic e
        "ｓｈｏｗ version",  # full-width letters
        "show version​",  # zero width space
        "show version",  # no-break space
        "show version é",
    ],
)
def test_non_ascii_text_is_refused(raw: str) -> None:
    with pytest.raises(cp.CommandNotAllowedError):
        cp.check_command(raw)


def test_uppercase_show_is_accepted_and_normalised_to_lowercase_keyword() -> None:
    assert cp.check_command("SHOW Version") == "show Version"


def test_over_long_commands_are_refused() -> None:
    cp.check_command("show " + "a" * (cp.MAX_COMMAND_CHARS - 5))
    with pytest.raises(cp.CommandNotAllowedError):
        cp.check_command("show " + "a" * cp.MAX_COMMAND_CHARS)


def test_the_reason_never_echoes_the_command() -> None:
    with pytest.raises(cp.CommandNotAllowedError) as info:
        cp.check_command("reload SECRET-TEXT")

    assert "SECRET-TEXT" not in str(info.value)


def test_check_commands_normalises_all_and_caps_the_count() -> None:
    assert cp.check_commands(["show  version", "show ip route"]) == [
        "show version",
        "show ip route",
    ]
    with pytest.raises(cp.CommandNotAllowedError):
        cp.check_commands([])
    with pytest.raises(cp.CommandNotAllowedError):
        cp.check_commands(["show version"] * (cp.MAX_COMMANDS + 1))


def test_check_commands_refuses_the_whole_list_if_one_is_bad() -> None:
    with pytest.raises(cp.CommandNotAllowedError):
        cp.check_commands(["show version", "reload"])


def test_repeated_commands_are_run_once() -> None:
    assert cp.check_commands(["show version", "show  version"]) == ["show version"]


@pytest.mark.parametrize(
    "raw",
    [
        "show run | count foo",
        "show run | no-more x",
        "show run | display set extra",
        "show run | include " + "a" * (cp.MAX_FILTER_PATTERN_CHARS + 1),
        "show version \x7f",
        "show version\x0b",
        "show version\x0c",
        "show 'version'",
        'show "version"',
        "show version ?",
        "show version !",
    ],
)
def test_filter_arguments_and_odd_characters_are_checked(raw: str) -> None:
    with pytest.raises(cp.CommandNotAllowedError):
        cp.check_command(raw)


def test_a_filter_pattern_at_the_limit_is_allowed() -> None:
    pattern = "a" * cp.MAX_FILTER_PATTERN_CHARS

    assert cp.check_command(f"show run | include {pattern}") == f"show run | include {pattern}"

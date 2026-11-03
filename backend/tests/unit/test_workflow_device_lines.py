import pytest

from services.workflow.device_lines import (
    device_line,
    enabled_device_input_readers,
    parse_ipv4_literal,
)


@pytest.mark.parametrize("value", ["10.0.0.1", "192.168.1.20", "8.8.8.8"])
def test_ipv4_literals_are_accepted(value: str) -> None:
    assert parse_ipv4_literal(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        " 10.0.0.1",
        "10.0.0.1 ",
        "10.0.0.1\n10.0.0.2",
        "10.0.0.1,10.0.0.2",
        "10.0.0.0/24",
        "10.0.0.1-5",
        "router1",
        "0x0a.0.0.1",
        "10.0.0",
        "10.0.0.256",
        "::1",
        "010.0.0.1",
        "١٠.0.0.1",
    ],
)
def test_anything_else_is_refused(value: str) -> None:
    assert parse_ipv4_literal(value) is None


def test_line_formats() -> None:
    assert device_line(name="sw1", ip="10.0.0.1", network_driver="cisco_xe", platform=None) == (
        "sw1,10.0.0.1,cisco_xe"
    )
    assert device_line(name="sw1", ip="10.0.0.1", network_driver=None, platform=None) == (
        "sw1,10.0.0.1"
    )
    assert device_line(name=None, ip="10.0.0.1", network_driver=None, platform=None) == "10.0.0.1"
    assert device_line(name="a,b", ip="10.0.0.1", network_driver=None, platform=None) == "10.0.0.1"
    assert device_line(name=None, ip=None, network_driver=None, platform=None) is None


def test_readers_are_enabled_get_from_user_steps_on_that_input() -> None:
    def node(node_id: str, kind: str, param: str, disabled: bool = False) -> dict:
        data = {"kind": kind, "pluginConfig": {"device_param": param}, "disabled": disabled}
        return {"id": node_id, "data": data}

    nodes = [
        node("a", "get-from-user", "devs"),
        node("b", "get-from-user", "devs", disabled=True),
        node("c", "get-from-user", "other"),
        node("d", "send-commands", "devs"),
    ]
    assert enabled_device_input_readers(nodes, "devs") == ["a"]

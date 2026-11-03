"""build_run_inputs: the devices and credential inputs are filled here and nowhere else."""

from __future__ import annotations

import pytest

from services.ai_assistant.released_run_builder import (
    MAX_DEVICES,
    ProposedDevice,
    ReleasedRunError,
    build_run_inputs,
    device_lines,
)

SW1 = ProposedDevice(ip="10.0.0.1", name="sw1", network_driver="cisco_xe", platform="ios")
NEW = ProposedDevice(ip="192.168.5.9", in_inventory=False)


def build(**kw):
    args = {
        "devices_input": "target_devices",
        "credential_inputs": ["cred"],
        "allow_free_ip": False,
        "model_inputs": {"features": "ospf"},
        "devices": [SW1],
        "credentials": {"cred": "lab-ssh"},
        "free_ip_driver": None,
    }
    return build_run_inputs(**{**args, **kw})


def test_joins_model_inputs_devices_and_the_users_credential() -> None:
    assert build() == {
        "features": "ospf",
        "cred": "lab-ssh",
        "target_devices": "sw1,10.0.0.1,cisco_xe",
    }


def test_one_line_per_device() -> None:
    other = ProposedDevice(ip="10.0.0.2", name="sw2")
    assert build(devices=[SW1, other])["target_devices"].splitlines() == [
        "sw1,10.0.0.1,cisco_xe",
        "sw2,10.0.0.2",
    ]


def test_a_free_address_is_a_bare_ip_or_gets_the_users_driver() -> None:
    assert device_lines([NEW], None) == "192.168.5.9"
    assert device_lines([NEW], "cisco_ios") == ",192.168.5.9,cisco_ios"
    # the inventory device keeps its own driver, whatever the user chose for free addresses
    assert device_lines([SW1, NEW], "juniper_junos").splitlines()[0] == "sw1,10.0.0.1,cisco_xe"


def test_free_address_needs_the_release_to_allow_it() -> None:
    with pytest.raises(ReleasedRunError, match="inventory"):
        build(devices=[NEW])
    assert build(devices=[NEW], allow_free_ip=True)["target_devices"] == "192.168.5.9"


@pytest.mark.parametrize("name", ["target_devices", "cred"])
def test_the_model_cannot_set_the_devices_or_credential_inputs(name: str) -> None:
    with pytest.raises(ReleasedRunError, match="cannot be set"):
        build(model_inputs={name: "evil"})


def test_credentials_must_match_the_declared_inputs_exactly() -> None:
    with pytest.raises(ReleasedRunError, match="Choose a credential"):
        build(credentials={})
    with pytest.raises(ReleasedRunError, match="Choose a credential"):
        build(credentials={"cred": "  "})
    with pytest.raises(ReleasedRunError, match="Not a credential input"):
        build(credentials={"cred": "a", "features": "b"})


def test_devices_rules() -> None:
    with pytest.raises(ReleasedRunError, match="at least one"):
        build(devices=[])
    with pytest.raises(ReleasedRunError, match="does not take devices"):
        build(devices_input=None, credential_inputs=["cred"])
    with pytest.raises(ReleasedRunError, match="At most"):
        build(devices=[ProposedDevice(ip=f"10.0.1.{i}") for i in range(MAX_DEVICES + 1)])


def test_a_workflow_without_devices_or_credentials_needs_neither() -> None:
    assert build(devices_input=None, credential_inputs=[], devices=[], credentials={}) == {
        "features": "ospf"
    }


def test_a_device_that_is_not_an_ipv4_is_refused_before_it_can_reach_a_line() -> None:
    bad = ProposedDevice(ip="10.0.0.1\n10.0.0.2", in_inventory=False)
    with pytest.raises(ReleasedRunError, match="no valid IPv4"):
        build(devices=[bad], allow_free_ip=True)

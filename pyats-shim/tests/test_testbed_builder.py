import pytest

from app.testbed_builder import TestbedBuildError, build_testbed_dict


def test_build_testbed_dict_minimal_device():
    testbed = build_testbed_dict(
        [{"name": "sw1", "host": "10.0.0.1", "os": "iosxe", "username": "admin", "password": "admin"}]
    )
    device = testbed["devices"]["sw1"]
    assert device["os"] == "iosxe"
    assert device["type"] == "iosxe"
    assert device["connections"]["cli"] == {"protocol": "ssh", "ip": "10.0.0.1"}
    assert device["credentials"]["default"] == {"username": "admin", "password": "admin"}


def test_build_testbed_dict_uses_platform_and_port_when_given():
    testbed = build_testbed_dict(
        [
            {
                "name": "sw1",
                "host": "10.0.0.1",
                "os": "iosxe",
                "platform": "csr1000v",
                "port": 2222,
                "username": "admin",
                "password": "admin",
            }
        ]
    )
    device = testbed["devices"]["sw1"]
    assert device["type"] == "csr1000v"
    assert device["connections"]["cli"]["port"] == 2222


def test_build_testbed_dict_requires_at_least_one_device():
    with pytest.raises(TestbedBuildError):
        build_testbed_dict([])


def test_build_testbed_dict_requires_all_fields():
    with pytest.raises(TestbedBuildError):
        build_testbed_dict([{"name": "sw1", "host": "10.0.0.1", "os": "iosxe"}])


def test_build_testbed_dict_rejects_duplicate_names():
    device = {
        "name": "sw1",
        "host": "10.0.0.1",
        "os": "iosxe",
        "username": "admin",
        "password": "admin",
    }
    with pytest.raises(TestbedBuildError):
        build_testbed_dict([device, device])

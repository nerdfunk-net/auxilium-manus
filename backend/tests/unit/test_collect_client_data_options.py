"""Configuration parsing of the collect-client-data step."""

from __future__ import annotations

import pytest

from workflow_steps.collect_client_data.config import get_config
from workflow_steps.collect_client_data.options import parse_options


def test_defaults_collect_ip_mac_and_vrfs_but_not_hostnames() -> None:
    options = parse_options(get_config())

    assert options.collect_ip_address is True
    assert options.collect_mac_address is True
    assert options.collect_vrfs is True
    assert options.collect_hostname is False
    assert options.dry_run is False
    assert options.network_driver_override is None
    assert options.dns_timeout_seconds == 2.0
    assert options.dns_concurrency == 20


def test_flags_accept_strings() -> None:
    options = parse_options({**get_config(), "collect_mac_address": "false", "dry_run": "true"})

    assert options.collect_mac_address is False
    assert options.dry_run is True


def test_hostname_collection_needs_arp() -> None:
    with pytest.raises(ValueError, match="collect_hostname"):
        parse_options({**get_config(), "collect_ip_address": False, "collect_hostname": True})


def test_at_least_one_table_must_be_collected() -> None:
    with pytest.raises(ValueError, match="collect_ip_address"):
        parse_options({**get_config(), "collect_ip_address": False, "collect_mac_address": False})


def test_vrfs_are_only_effective_with_arp() -> None:
    options = parse_options({**get_config(), "collect_ip_address": False})

    assert options.collect_vrfs is False


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("dns_timeout_seconds", 0),
        ("dns_timeout_seconds", 31),
        ("dns_timeout_seconds", "soon"),
        ("dns_concurrency", 0),
        ("dns_concurrency", 101),
        ("read_timeout", "x"),
    ],
)
def test_out_of_range_values_are_rejected(key: str, value: object) -> None:
    with pytest.raises(ValueError, match=key):
        parse_options({**get_config(), key: value})


def test_driver_override_is_trimmed() -> None:
    options = parse_options({**get_config(), "network_driver_override": " cisco_xe "})

    assert options.network_driver_override == "cisco_xe"


def test_neighbours_are_off_by_default_and_can_be_switched_on() -> None:
    assert parse_options(get_config()).collect_neighbors is False
    assert parse_options({**get_config(), "collect_neighbors": True}).collect_neighbors is True


def test_a_config_without_the_flag_does_not_collect_neighbours() -> None:
    options = parse_options({"collect_ip_address": True})

    assert options.collect_neighbors is False


def test_neighbours_do_not_need_the_other_tables_but_something_must_be_collected() -> None:
    options = parse_options(
        {
            **get_config(),
            "collect_ip_address": False,
            "collect_mac_address": False,
            "collect_neighbors": True,
        }
    )
    assert options.collect_neighbors is True and options.collect_ip_address is False
    with pytest.raises(ValueError, match="collect_ip_address"):
        parse_options(
            {
                **get_config(),
                "collect_ip_address": False,
                "collect_mac_address": False,
                "collect_neighbors": False,
            }
        )

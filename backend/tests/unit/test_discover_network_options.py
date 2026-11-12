"""Configuration parsing of the discover-network step."""

from __future__ import annotations

import ipaddress

import pytest

from workflow_steps.discover_network.config import get_config
from workflow_steps.discover_network.options import STEP_ID, parse_options


def test_defaults_do_not_follow_and_parse() -> None:
    options = parse_options(get_config())
    assert STEP_ID == "discover-network"
    assert options.follow_neighbors is False
    assert options.prefixes == ()
    assert options.follow_only_infrastructure is True
    assert (options.max_devices, options.max_depth, options.concurrency) == (50, 5, 5)
    assert options.dry_run is False
    assert options.network_driver_override is None


def test_following_needs_at_least_one_prefix() -> None:
    with pytest.raises(ValueError, match="permitted_prefixes"):
        parse_options({**get_config(), "follow_neighbors": True})


def test_following_with_prefixes_parses_them() -> None:
    options = parse_options(
        {**get_config(), "follow_neighbors": True, "permitted_prefixes": ["10.1.0.0/16"]}
    )
    assert options.prefixes == (ipaddress.ip_network("10.1.0.0/16"),)


def test_string_booleans_are_accepted() -> None:
    options = parse_options({**get_config(), "follow_neighbors": "false", "dry_run": "true"})
    assert (options.follow_neighbors, options.dry_run) == (False, True)


def test_invalid_prefixes_are_rejected_even_when_not_following() -> None:
    with pytest.raises(ValueError, match="discover-network"):
        parse_options({**get_config(), "permitted_prefixes": ["0.0.0.0/0"]})


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("max_devices", 0),
        ("max_devices", 501),
        ("max_depth", 0),
        ("max_depth", 21),
        ("concurrency", 0),
        ("concurrency", 21),
        ("max_devices", "many"),
    ],
)
def test_numeric_limits_are_bounded(key: str, value: object) -> None:
    with pytest.raises(ValueError, match="discover-network"):
        parse_options({**get_config(), key: value})


def test_override_is_trimmed() -> None:
    options = parse_options({**get_config(), "network_driver_override": " cisco_xe "})
    assert options.network_driver_override == "cisco_xe"

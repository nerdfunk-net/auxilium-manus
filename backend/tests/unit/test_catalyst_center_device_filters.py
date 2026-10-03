"""Tests for CatalystCenterDeviceFilters: parsing, server query params, CIDR handling.

Server semantics (verified live on the DevNet sandbox): matching is case-sensitive and
full-string, ``.*`` is the only wildcard, a repeated query parameter means OR, and different
filters combine with AND. There is no CIDR filter, so CIDR is a prefix prefilter + client check.
"""

from __future__ import annotations

import pytest

from services.catalyst_center.common.exceptions import CatalystCenterValidationError
from services.catalyst_center.device_filters import CatalystCenterDeviceFilters


def _filters(**raw):
    return CatalystCenterDeviceFilters.from_config(raw)


class TestFromConfig:
    def test_none_and_empty_are_empty(self):
        assert CatalystCenterDeviceFilters.from_config(None).is_empty
        assert _filters().is_empty
        assert _filters(hostnames=[], roles=["", "  "]).is_empty

    def test_trims_dedupes_and_keeps_order(self):
        f = _filters(hostnames=[" sw1 ", "sw2", "sw1", ""])
        assert f.hostnames == ("sw1", "sw2")

    def test_every_filter_kind_is_accepted(self):
        f = _filters(
            hostnames=["a"],
            management_ips=["10.0.0.1"],
            families=["Switches and Hubs"],
            roles=["ACCESS"],
            software_types=["IOS-XE"],
            software_versions=["17.12.*"],
            platform_ids=["C9KV.*"],
            serial_numbers=["CML.*"],
            series=[".*Catalyst 9000.*"],
            device_types=[".*Virtual.*"],
            reachability_statuses=["Reachable"],
            collection_statuses=["Managed"],
            cidr="10.0.0.0/24",
        )
        assert not f.is_empty
        assert f.cidr == "10.0.0.0/24"

    def test_values_are_not_regex_translated(self):
        # the server only understands ".*"; everything else must reach it untouched
        assert _filters(hostnames=["sw|x[1]"]).hostnames == ("sw|x[1]",)

    @pytest.mark.parametrize("bad", ["a", 5, {"x": 1}, [1], [None], [["x"]]])
    def test_values_must_be_a_list_of_strings(self, bad):
        with pytest.raises(CatalystCenterValidationError):
            _filters(hostnames=bad)

    def test_unknown_filter_key_is_rejected(self):
        with pytest.raises(CatalystCenterValidationError, match="Unknown filter"):
            _filters(hostname=["sw1"])  # typo: singular

    def test_non_mapping_config_is_rejected(self):
        with pytest.raises(CatalystCenterValidationError):
            CatalystCenterDeviceFilters.from_config(["sw1"])  # type: ignore[arg-type]

    def test_too_many_values_is_rejected(self):
        with pytest.raises(CatalystCenterValidationError, match="at most"):
            _filters(hostnames=[f"sw{i}" for i in range(51)])

    def test_overlong_value_is_rejected(self):
        with pytest.raises(CatalystCenterValidationError):
            _filters(hostnames=["x" * 300])

    def test_control_characters_are_rejected(self):
        with pytest.raises(CatalystCenterValidationError):
            _filters(hostnames=["sw1\x00"])

    @pytest.mark.parametrize("cidr", ["10.0.0.0/33", "not-an-ip", "10.0.0.0/24/8", 5])
    def test_invalid_cidr_is_rejected(self, cidr):
        with pytest.raises(CatalystCenterValidationError):
            _filters(cidr=cidr)

    def test_blank_cidr_means_unset(self):
        assert _filters(cidr="   ").cidr is None

    def test_cidr_is_normalised(self):
        assert _filters(cidr="10.10.20.7/24").cidr == "10.10.20.0/24"
        assert _filters(cidr=" 10.10.20.7 ").cidr == "10.10.20.7/32"

    def test_is_immutable(self):
        f = _filters(hostnames=["a"])
        with pytest.raises(AttributeError):
            f.hostnames = ("b",)  # type: ignore[misc]


class TestQueryParams:
    def test_maps_to_intent_api_names_as_lists(self):
        f = _filters(
            hostnames=["sw1", "sw2"],
            families=["Routers"],
            roles=["CORE"],
            software_types=["IOS-XE"],
            software_versions=["17.12.1"],
            platform_ids=["C9300"],
            serial_numbers=["FOC1"],
            series=["S"],
            device_types=["T"],
            reachability_statuses=["Reachable"],
            collection_statuses=["Managed"],
            management_ips=["10.0.0.1"],
        )
        assert f.to_query_params() == {
            "hostname": ["sw1", "sw2"],
            "managementIpAddress": ["10.0.0.1"],
            "family": ["Routers"],
            "role": ["CORE"],
            "softwareType": ["IOS-XE"],
            "softwareVersion": ["17.12.1"],
            "platformId": ["C9300"],
            "serialNumber": ["FOC1"],
            "series": ["S"],
            "type": ["T"],
            "reachabilityStatus": ["Reachable"],
            "collectionStatus": ["Managed"],
        }

    def test_empty_filters_give_no_params(self):
        assert _filters().to_query_params() == {}

    def test_cidr_alone_becomes_prefix_prefilter(self):
        assert _filters(cidr="10.10.20.0/24").to_query_params() == {
            "managementIpAddress": ["10.10.20..*"]
        }

    def test_explicit_ips_win_over_cidr_prefilter_to_keep_and_semantics(self):
        f = _filters(management_ips=["10.10.20.5"], cidr="10.10.20.0/24")
        assert f.to_query_params() == {"managementIpAddress": ["10.10.20.5"]}
        assert f.matches_ip("10.10.20.5")
        assert not f.matches_ip("10.10.21.5")


class TestCidrPrefilter:
    @pytest.mark.parametrize(
        ("cidr", "expected"),
        [
            ("10.10.20.0/24", "10.10.20..*"),
            ("10.10.20.176/31", "10.10.20..*"),
            ("10.10.20.0/23", "10.10..*"),
            ("10.10.0.0/16", "10.10..*"),
            ("10.0.0.0/8", "10..*"),
            ("10.10.20.175/32", "10.10.20.175"),
            ("10.10.20.128/25", "10.10.20..*"),
            ("0.0.0.0/0", None),
            ("128.0.0.0/1", None),
            ("2001:db8::/32", None),
        ],
    )
    def test_prefilter(self, cidr, expected):
        assert _filters(cidr=cidr).cidr_prefilter() == expected

    def test_no_cidr_no_prefilter(self):
        assert _filters().cidr_prefilter() is None


class TestMatchesIp:
    def test_no_cidr_accepts_anything(self):
        f = _filters(hostnames=["a"])
        assert f.matches_ip(None)
        assert f.matches_ip("anything")

    @pytest.mark.parametrize(
        ("ip", "expected"),
        [
            ("10.10.20.176", True),
            ("10.10.20.177", True),
            ("10.10.20.178", False),
            (None, False),
            ("", False),
            ("garbage", False),
            ("2001:db8::1", False),
        ],
    )
    def test_cidr_membership(self, ip, expected):
        assert _filters(cidr="10.10.20.176/31").matches_ip(ip) is expected

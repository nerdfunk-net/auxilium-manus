import ipaddress
import unittest

from manus_agent.ranges import RangeError, expand_ranges, parse_networks


class ExpandRangesTests(unittest.TestCase):
    def test_single_address(self) -> None:
        assert expand_ranges("10.0.0.5", max_hosts=10) == ["10.0.0.5"]

    def test_cidr_excludes_network_and_broadcast(self) -> None:
        hosts = expand_ranges("10.0.0.0/30", max_hosts=10)
        assert hosts == ["10.0.0.1", "10.0.0.2"]

    def test_slash_24_has_254_hosts(self) -> None:
        hosts = expand_ranges("192.168.1.0/24", max_hosts=1000)
        assert len(hosts) == 254
        assert hosts[0] == "192.168.1.1" and hosts[-1] == "192.168.1.254"

    def test_slash_31_and_32_keep_every_address(self) -> None:
        assert expand_ranges("10.0.0.0/31", max_hosts=10) == ["10.0.0.0", "10.0.0.1"]
        assert expand_ranges("10.0.0.9/32", max_hosts=10) == ["10.0.0.9"]

    def test_cidr_with_host_bits_is_taken_as_its_network(self) -> None:
        assert expand_ranges("10.0.0.7/30", max_hosts=10) == ["10.0.0.5", "10.0.0.6"]

    def test_full_range_is_inclusive(self) -> None:
        assert expand_ranges("10.0.0.5-10.0.0.7", max_hosts=10) == [
            "10.0.0.5",
            "10.0.0.6",
            "10.0.0.7",
        ]

    def test_short_range_replaces_the_last_octet(self) -> None:
        assert expand_ranges("10.0.0.5-7", max_hosts=10) == ["10.0.0.5", "10.0.0.6", "10.0.0.7"]

    def test_list_separated_by_commas_and_newlines_is_deduplicated_and_sorted(self) -> None:
        hosts = expand_ranges("10.0.0.9, 10.0.0.1-2\n10.0.0.2", max_hosts=10)
        assert hosts == ["10.0.0.1", "10.0.0.2", "10.0.0.9"]

    def test_whitespace_around_the_dash_is_fine(self) -> None:
        assert expand_ranges("10.0.0.1 - 10.0.0.2", max_hosts=10) == ["10.0.0.1", "10.0.0.2"]

    def test_more_hosts_than_the_cap_is_refused_before_expanding(self) -> None:
        with self.assertRaises(RangeError) as caught:
            expand_ranges("10.0.0.0/8", max_hosts=4096)
        assert "4096" in str(caught.exception)

    def test_cap_applies_to_the_total_of_a_list(self) -> None:
        with self.assertRaises(RangeError):
            expand_ranges("10.0.0.0/30, 10.0.1.0/30", max_hosts=3)

    def test_reversed_range_is_refused(self) -> None:
        with self.assertRaises(RangeError):
            expand_ranges("10.0.0.9-10.0.0.1", max_hosts=10)

    def test_short_range_above_255_is_refused(self) -> None:
        with self.assertRaises(RangeError):
            expand_ranges("10.0.0.1-300", max_hosts=1000)

    def test_ipv6_is_refused(self) -> None:
        with self.assertRaises(RangeError):
            expand_ranges("2001:db8::/120", max_hosts=1000)

    def test_hostnames_are_refused(self) -> None:
        with self.assertRaises(RangeError):
            expand_ranges("example.com", max_hosts=10)

    def test_empty_and_non_text_are_refused(self) -> None:
        for value in ("", "  ,\n ", None, 5, ["10.0.0.1"]):
            with self.subTest(value=value), self.assertRaises(RangeError):
                expand_ranges(value, max_hosts=10)  # type: ignore[arg-type]

    def test_error_does_not_echo_a_huge_input(self) -> None:
        with self.assertRaises(RangeError) as caught:
            expand_ranges("x" * 5000, max_hosts=10)
        assert len(str(caught.exception)) < 200

    def test_option_looking_input_is_just_invalid(self) -> None:
        with self.assertRaises(RangeError):
            expand_ranges("-f /etc/passwd", max_hosts=10)

    def test_allowed_networks_restrict_every_host(self) -> None:
        allowed = parse_networks("10.0.0.0/24, 192.168.0.0/16")
        assert expand_ranges("10.0.0.1-3", max_hosts=10, allowed=allowed) == [
            "10.0.0.1",
            "10.0.0.2",
            "10.0.0.3",
        ]
        with self.assertRaises(RangeError) as caught:
            expand_ranges("10.0.0.250-10.0.1.2", max_hosts=100, allowed=allowed)
        assert "allowed" in str(caught.exception)

    def test_allowed_check_happens_before_the_host_cap_expansion(self) -> None:
        allowed = parse_networks("10.0.0.0/24")
        with self.assertRaises(RangeError):
            expand_ranges("172.16.0.0/12", max_hosts=10_000_000, allowed=allowed)


class NeverPingableTests(unittest.TestCase):
    def test_special_purpose_addresses_are_refused_even_without_an_allow_list(self) -> None:
        for text in (
            "0.0.0.0",
            "0.1.2.3",
            "127.0.0.1",
            "169.254.169.254",
            "169.254.0.0/24",
            "224.0.0.1",
            "239.255.255.250",
            "240.0.0.1",
            "255.255.255.255",
            "10.0.0.1, 127.0.0.1",
            "126.255.255.250-127.0.0.2",
        ):
            with self.subTest(text=text), self.assertRaises(RangeError) as caught:
                expand_ranges(text, max_hosts=100)
            assert "not pingable" in str(caught.exception)

    def test_refused_even_when_the_allow_list_would_contain_them(self) -> None:
        everything = parse_networks("0.0.0.0/0")
        with self.assertRaises(RangeError):
            expand_ranges("169.254.169.254", max_hosts=10, allowed=everything)
        assert expand_ranges("8.8.8.8", max_hosts=10, allowed=everything) == ["8.8.8.8"]


class ParseNetworksTests(unittest.TestCase):
    def test_empty_means_no_restriction(self) -> None:
        assert parse_networks("") == ()
        assert parse_networks(None) == ()

    def test_parses_a_list(self) -> None:
        assert parse_networks("10.0.0.0/8,192.168.0.0/16") == (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("192.168.0.0/16"),
        )

    def test_invalid_entry_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            parse_networks("10.0.0.0/8, nonsense")

import logging
import unittest
from unittest.mock import AsyncMock, patch

from manus_agent import inventory
from manus_agent.fping import FpingError, HostResult
from manus_agent.inventory import MAX_DEVICES, list_devices
from manus_agent.inventory_config import parse_inventory_config
from manus_agent.nautobot import NautobotError


def make_config(*, dns: bool = False, **scan):
    raw = {
        "nautobot": {"url": "http://nb", "token": "t"},
        "scan": scan,
        "resolve_dns": {"enabled": dns},
    }
    return parse_inventory_config(raw, {})


def fake_fping(reachable: set[str]):
    async def run(hosts, *, count, timeout_ms):
        return [
            HostResult(ip, ip in reachable, 0.5 if ip in reachable else None, 0) for ip in hosts
        ]

    return AsyncMock(side_effect=run)


def with_prefixes(prefixes):
    return patch.object(inventory, "fetch_prefixes_by_tag", AsyncMock(return_value=prefixes))


async def run(attributes, config=None, *, params=None):
    return await list_devices(params or {}, {"attributes": attributes}, config or make_config())


class HappyPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_builds_the_inventory_from_the_reachable_hosts(self) -> None:
        ping = fake_fping({"192.168.178.20", "192.168.178.1"})
        with (
            with_prefixes(["192.168.178.0/24"]) as fetch,
            patch.object(inventory, "run_fping", ping),
        ):
            answer = await run({"tag": " ping "})
        fetch.assert_awaited_once()
        assert fetch.await_args.args[1] == "ping"
        assert answer == {
            "devices": [
                {"name": "192.168.178.1", "ip_address": "192.168.178.1", "network_driver": ""},
                {"name": "192.168.178.20", "ip_address": "192.168.178.20", "network_driver": ""},
            ]
        }
        assert len(ping.await_args.args[0]) == 254  # network and broadcast address left out

    async def test_resolved_names_replace_the_address_as_name(self) -> None:
        names = AsyncMock(return_value={"192.168.1.1": "gw.example.net", "192.168.1.2": None})
        with (
            with_prefixes(["192.168.1.0/30"]),
            patch.object(inventory, "run_fping", fake_fping({"192.168.1.1", "192.168.1.2"})),
            patch.object(inventory, "resolve_names", names),
        ):
            answer = await run({"tag": "ping"}, make_config(dns=True))
        assert [d["name"] for d in answer["devices"]] == ["gw.example.net", "192.168.1.2"]
        names.assert_awaited_once()
        assert names.await_args.kwargs["timeout"] == 2

    async def test_the_log_says_why_names_are_missing(self) -> None:
        import socket

        def gethostbyaddr(ip: str):
            if ip.endswith(".1"):
                return ("gw.example.net", [], [ip])
            if ip.endswith(".2"):
                raise socket.herror(1, "Unknown host")
            raise socket.gaierror(-3, "Temporary failure in name resolution")

        with (
            with_prefixes(["192.168.1.0/29"]),
            patch.object(
                inventory, "run_fping", fake_fping({"192.168.1.1", "192.168.1.2", "192.168.1.3"})
            ),
            patch.object(inventory.socket, "gethostbyaddr", gethostbyaddr),
            self.assertLogs(inventory.logger, logging.INFO) as logs,
        ):
            answer = await run({"tag": "ping"}, make_config(dns=True))
        assert [d["name"] for d in answer["devices"]] == [
            "gw.example.net",
            "192.168.1.2",
            "192.168.1.3",
        ]
        text = "\n".join(logs.output)
        assert "reverse DNS: 1 of 3 named (no_ptr_record=1, resolved=1, resolver_error=1)" in text
        assert "resolver_error, for example: gaierror: [Errno -3] Temporary failure" in text
        assert "WARNING" not in text

    async def test_a_warning_when_no_host_got_a_name(self) -> None:
        import socket

        def gethostbyaddr(ip: str):
            raise socket.herror(1, "Unknown host")

        with (
            with_prefixes(["192.168.1.0/30"]),
            patch.object(inventory, "run_fping", fake_fping({"192.168.1.1"})),
            patch.object(inventory.socket, "gethostbyaddr", gethostbyaddr),
            self.assertLogs(inventory.logger, logging.INFO) as logs,
        ):
            await run({"tag": "ping"}, make_config(dns=True))
        text = "\n".join(logs.output)
        assert "reverse DNS: 0 of 1 named (no_ptr_record=1)" in text
        assert "WARNING" in text and "named none of 1 hosts" in text

    async def test_herror_codes_tell_no_record_from_a_failed_lookup(self) -> None:
        import socket

        def gethostbyaddr(ip: str):
            if ip.endswith(".1"):
                raise socket.herror(1, "Unknown host")  # HOST_NOT_FOUND
            if ip.endswith(".2"):
                raise socket.herror(4, "No data")  # NO_DATA
            raise socket.herror(2, "Host name lookup failure")  # TRY_AGAIN

        with (
            with_prefixes(["192.168.1.0/29"]),
            patch.object(
                inventory, "run_fping", fake_fping({"192.168.1.1", "192.168.1.2", "192.168.1.3"})
            ),
            patch.object(inventory.socket, "gethostbyaddr", gethostbyaddr),
            self.assertLogs(inventory.logger, logging.INFO) as logs,
        ):
            await run({"tag": "ping"}, make_config(dns=True))
        text = "\n".join(logs.output)
        assert "(no_ptr_record=2, resolver_error=1)" in text
        assert "herror: [Errno 2] Host name lookup failure" in text

    async def test_other_lookup_errors_are_counted(self) -> None:
        def gethostbyaddr(ip: str):
            raise UnicodeError("bad name")

        with (
            with_prefixes(["192.168.1.0/30"]),
            patch.object(inventory, "run_fping", fake_fping({"192.168.1.1"})),
            patch.object(inventory.socket, "gethostbyaddr", gethostbyaddr),
            self.assertLogs(inventory.logger, logging.INFO) as logs,
        ):
            await run({"tag": "ping"}, make_config(dns=True))
        assert "other_error=1" in "\n".join(logs.output)

    async def test_slow_lookups_are_counted_as_timed_out(self) -> None:
        import threading

        release = threading.Event()

        def gethostbyaddr(ip: str):
            release.wait(5)
            return ("late.example.net", [], [ip])

        config = parse_inventory_config(
            {
                "nautobot": {"url": "http://nb", "token": "t"},
                "resolve_dns": {"enabled": True, "timeout_seconds": 0.5},
            },
            {},
        )
        try:
            with (
                with_prefixes(["192.168.1.0/30"]),
                patch.object(inventory, "run_fping", fake_fping({"192.168.1.1"})),
                patch.object(inventory.socket, "gethostbyaddr", gethostbyaddr),
                self.assertLogs(inventory.logger, logging.INFO) as logs,
            ):
                await run({"tag": "ping"}, config)
        finally:
            release.set()
        assert "timed_out_or_skipped=1" in "\n".join(logs.output)

    async def test_unusable_ptr_names_fall_back_to_the_address(self) -> None:
        ips = {"192.168.1.1", "192.168.1.2", "192.168.1.3", "192.168.1.4", "192.168.1.5"}
        names = AsyncMock(
            return_value={
                "192.168.1.1": "metadata.google.internal",
                "192.168.1.2": "127.0.0.1",
                "192.168.1.3": "bad name\nwith newline",
                "192.168.1.4": "x" * 300,
                "192.168.1.5": "router-1.lan_example.net",
            }
        )
        with (
            with_prefixes(["192.168.1.0/29"]),
            patch.object(inventory, "run_fping", fake_fping(ips)),
            patch.object(inventory, "resolve_names", names),
            self.assertLogs(inventory.logger, logging.INFO) as logs,
        ):
            answer = await run({"tag": "ping"}, make_config(dns=True))
        assert [d["name"] for d in answer["devices"]] == [
            "192.168.1.1",
            "192.168.1.2",
            "192.168.1.3",
            "192.168.1.4",
            "router-1.lan_example.net",
        ]
        assert "4 name(s) are not usable host names" in "\n".join(logs.output)

    async def test_dns_is_not_used_when_off(self) -> None:
        names = AsyncMock()
        with (
            with_prefixes(["192.168.1.0/30"]),
            patch.object(inventory, "run_fping", fake_fping({"192.168.1.1"})),
            patch.object(inventory, "resolve_names", names),
        ):
            await run({"tag": "ping"})
        names.assert_not_awaited()

    async def test_each_prefix_is_pinged_and_overlaps_are_pinged_once(self) -> None:
        ping = fake_fping({"10.0.0.1", "10.0.1.1"})
        with (
            with_prefixes(["10.0.0.0/30", "10.0.0.0/29", "10.0.1.0/30"]),
            patch.object(inventory, "run_fping", ping),
        ):
            answer = await run({"tag": "ping"})
        pinged = [ip for call in ping.await_args_list for ip in call.args[0]]
        assert len(pinged) == len(set(pinged))
        assert len(ping.await_args_list) == 3
        assert [d["ip_address"] for d in answer["devices"]] == ["10.0.0.1", "10.0.1.1"]

    async def test_a_duplicate_prefix_is_not_pinged_again(self) -> None:
        ping = fake_fping({"10.0.0.1"})
        with (
            with_prefixes(["10.0.0.0/30", "10.0.0.0/30"]),
            patch.object(inventory, "run_fping", ping),
        ):
            answer = await run({"tag": "ping"})
        assert len(ping.await_args_list) == 1
        assert len(answer["devices"]) == 1

    async def test_fping_settings_come_from_the_config(self) -> None:
        ping = fake_fping({"10.0.0.1"})
        with with_prefixes(["10.0.0.0/30"]), patch.object(inventory, "run_fping", ping):
            await run({"tag": "ping"}, make_config(count=3, timeout_ms=900))
        assert ping.await_args.kwargs == {"count": 3, "timeout_ms": 900}

    async def test_ipv6_prefixes_are_skipped_and_logged(self) -> None:
        with (
            with_prefixes(["2001:db8::/64", "10.0.0.0/30"]),
            patch.object(inventory, "run_fping", fake_fping({"10.0.0.1"})),
            self.assertLogs(inventory.logger, logging.INFO) as logs,
        ):
            answer = await run({"tag": "ping"})
        assert len(answer["devices"]) == 1
        assert any("skipped 1 IPv6" in line for line in logs.output)


class FailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_attributes(self) -> None:
        for attributes, pattern in (
            ({}, "'tag' is required"),
            ({"tag": ""}, "'tag' is required"),
            ({"tag": 5}, "'tag' is required"),
            ({"tag": "x" * 65}, "at most 64"),
            ({"tag": "a\nb"}, "control characters"),
            ({"tag": "ping", "site": "x"}, "unsupported attribute: site"),
            ({"tag": "ping", "site": "x", "role": "y"}, "role, site"),
            ("tag", "JSON object"),
        ):
            with self.subTest(attributes=attributes), self.assertRaisesRegex(ValueError, pattern):
                await run(attributes)

    async def test_nothing_is_fetched_for_a_bad_request(self) -> None:
        with with_prefixes([]) as fetch, self.assertRaises(ValueError):
            await run({})
        fetch.assert_not_awaited()

    async def test_no_prefix_with_the_tag(self) -> None:
        with with_prefixes([]), self.assertRaisesRegex(ValueError, "no Nautobot prefix"):
            await run({"tag": "ping"})

    async def test_only_ipv6_prefixes(self) -> None:
        with with_prefixes(["2001:db8::/64"]), self.assertRaisesRegex(ValueError, "no IPv4 prefix"):
            await run({"tag": "ping"})

    async def test_nautobot_errors_pass_through(self) -> None:
        failing = AsyncMock(side_effect=NautobotError("Nautobot answered HTTP 401"))
        with (
            patch.object(inventory, "fetch_prefixes_by_tag", failing),
            self.assertRaisesRegex(NautobotError, "401"),
        ):
            await run({"tag": "ping"})

    async def test_an_oversized_prefix_fails_before_any_packet(self) -> None:
        ping = fake_fping(set())
        with (
            with_prefixes(["10.0.0.0/30", "10.0.0.0/8"]),
            patch.object(inventory, "run_fping", ping),
        ):
            with (
                self.assertLogs(inventory.logger, logging.WARNING) as logs,
                self.assertRaisesRegex(ValueError, "prefix is refused: .*more than 4096") as caught,
            ):
                await run({"tag": "ping"})
        ping.assert_not_awaited()
        assert "10.0.0.0/8" not in str(caught.exception)  # the workflow run must not learn the CIDR
        assert "10.0.0.0/8" in "\n".join(logs.output)  # the operator does

    async def test_the_total_over_all_prefixes_is_limited(self) -> None:
        ping = fake_fping(set())
        with (
            with_prefixes(["10.0.0.0/24", "10.0.1.0/24"]),
            patch.object(inventory, "run_fping", ping),
            self.assertRaisesRegex(ValueError, "hold more than 300 addresses"),
        ):
            await run({"tag": "ping"}, make_config(max_hosts=300))
        ping.assert_not_awaited()

    async def test_a_prefix_outside_the_allowed_networks_fails(self) -> None:
        ping = fake_fping(set())
        with with_prefixes(["8.8.8.0/30"]), patch.object(inventory, "run_fping", ping):
            with self.assertRaisesRegex(ValueError, "outside the networks"):
                await run({"tag": "ping"})
        ping.assert_not_awaited()

    async def test_never_pingable_prefixes_fail_even_when_everything_is_allowed(self) -> None:
        config = make_config(allowed_networks=["0.0.0.0/0"])
        for prefix in ("127.0.0.0/30", "169.254.169.0/30", "224.0.0.0/30"):
            with self.subTest(prefix=prefix), with_prefixes([prefix]):
                with self.assertRaisesRegex(ValueError, "not pingable"):
                    await run({"tag": "ping"}, config)

    async def test_a_value_that_is_not_a_network(self) -> None:
        with with_prefixes(["not-a-prefix"]), self.assertRaisesRegex(ValueError, "not a network"):
            await run({"tag": "ping"})

    async def test_nothing_reachable_checks_that_icmp_works(self) -> None:
        async def ping(hosts, *, count, timeout_ms):
            return [HostResult(ip, False, None, 100) for ip in hosts]

        with (
            with_prefixes(["10.0.0.0/30"]),
            patch.object(inventory, "run_fping", AsyncMock(side_effect=ping)),
            self.assertRaisesRegex(FpingError, "NET_RAW"),
        ):
            await run({"tag": "ping"})

    async def test_nothing_reachable_but_icmp_works_is_an_empty_inventory(self) -> None:
        async def ping(hosts, *, count, timeout_ms):
            return [HostResult(ip, ip == "127.0.0.1", 0.1, 0) for ip in hosts]

        with (
            with_prefixes(["10.0.0.0/30"]),
            patch.object(inventory, "run_fping", AsyncMock(side_effect=ping)),
        ):
            assert await run({"tag": "ping"}) == {"devices": []}

    async def test_fping_failures_pass_through(self) -> None:
        failing = AsyncMock(side_effect=FpingError("fping failed (exit code 3)"))
        with (
            with_prefixes(["10.0.0.0/30"]),
            patch.object(inventory, "run_fping", failing),
            self.assertRaisesRegex(FpingError, "exit code 3"),
        ):
            await run({"tag": "ping"})

    async def test_more_devices_than_the_step_accepts(self) -> None:
        many = AsyncMock(
            return_value=[
                HostResult(f"10.{i // 256}.{i % 256}.1", True, 0.1, 0)
                for i in range(MAX_DEVICES + 1)
            ]
        )
        with (
            with_prefixes(["10.0.0.0/30"]),
            patch.object(inventory, "run_fping", many),
            self.assertRaisesRegex(ValueError, f"limit is {MAX_DEVICES}"),
        ):
            await run({"tag": "ping"})

"""Reverse DNS resolution for the collect-client-data step."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
import unittest

from workflow_steps.collect_client_data.dns import HostnameResolver


class HostnameResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_names_and_skips_failures(self) -> None:
        names = {"10.0.0.1": "pc1.example.net.", "10.0.0.3": "10.0.0.3"}

        def lookup(ip: str) -> str | None:
            if ip == "10.0.0.2":
                raise socket.herror("no PTR")
            return names.get(ip)

        async with HostnameResolver(timeout=1.0, concurrency=4, lookup=lookup) as resolver:
            result = await resolver.resolve(["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"])

        # Trailing dot removed; no PTR, a failure and "name equals the IP" are all left out.
        self.assertEqual(result, {"10.0.0.1": "pc1.example.net"})

    async def test_each_ip_is_looked_up_once_across_calls(self) -> None:
        calls: list[str] = []

        def lookup(ip: str) -> str | None:
            calls.append(ip)
            return "host.example.net"

        async with HostnameResolver(timeout=1.0, concurrency=4, lookup=lookup) as resolver:
            first = await resolver.resolve(["10.0.0.1", "10.0.0.1", "10.0.0.2"])
            second = await resolver.resolve(["10.0.0.2", "10.0.0.1"])

        self.assertEqual(sorted(calls), ["10.0.0.1", "10.0.0.2"])
        expected = {"10.0.0.1": "host.example.net", "10.0.0.2": "host.example.net"}
        self.assertEqual(first, expected)
        self.assertEqual(second, expected)

    async def test_a_slow_lookup_times_out_without_blocking_the_rest(self) -> None:
        release = threading.Event()

        def lookup(ip: str) -> str | None:
            if ip == "10.0.0.9":
                release.wait(2.0)
                return "slow.example.net"
            return "fast.example.net"

        started = time.monotonic()
        async with HostnameResolver(timeout=0.1, concurrency=4, lookup=lookup) as resolver:
            result = await resolver.resolve(["10.0.0.1", "10.0.0.9"])
            release.set()

        self.assertEqual(result, {"10.0.0.1": "fast.example.net"})
        self.assertLess(time.monotonic() - started, 1.5)

    async def test_concurrency_is_capped(self) -> None:
        lock = threading.Lock()
        state = {"active": 0, "peak": 0}

        def lookup(ip: str) -> str | None:
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            time.sleep(0.02)
            with lock:
                state["active"] -= 1
            return f"{ip}.example.net"

        ips = [f"10.0.0.{n}" for n in range(1, 13)]
        async with HostnameResolver(timeout=2.0, concurrency=3, lookup=lookup) as resolver:
            result = await resolver.resolve(ips)

        self.assertEqual(len(result), 12)
        self.assertLessEqual(state["peak"], 3)

    async def test_empty_input_needs_no_lookup(self) -> None:
        def lookup(ip: str) -> str | None:
            raise AssertionError(f"must not be called for {ip}")

        async with HostnameResolver(timeout=1.0, concurrency=2, lookup=lookup) as resolver:
            self.assertEqual(await resolver.resolve([]), {})


class HostnameResolverLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_unusable_addresses_are_not_looked_up(self) -> None:
        calls: list[str] = []

        def lookup(ip: str) -> str | None:
            calls.append(ip)
            return "h.example.net"

        unusable = ["0.0.0.0", "224.0.0.251", "255.255.255.255", "127.0.0.1", "ff02::1", "bogus"]
        async with HostnameResolver(timeout=1.0, concurrency=2, lookup=lookup) as resolver:
            result = await resolver.resolve([*unusable, "10.0.0.1"])

        self.assertEqual(calls, ["10.0.0.1"])
        self.assertEqual(result, {"10.0.0.1": "h.example.net"})

    async def test_the_number_of_addresses_per_resolver_is_capped(self) -> None:
        calls: list[str] = []

        def lookup(ip: str) -> str | None:
            calls.append(ip)
            return "h.example.net"

        ips = [f"10.0.0.{n}" for n in range(1, 21)]
        async with HostnameResolver(
            timeout=1.0, concurrency=4, lookup=lookup, max_addresses=5
        ) as resolver:
            first = await resolver.resolve(ips)
            again = await resolver.resolve(ips)

        self.assertEqual(len(calls), 5)
        self.assertEqual(len(first), 5)
        self.assertEqual(first, again)

    async def test_a_timed_out_lookup_keeps_holding_its_slot(self) -> None:
        lock = threading.Lock()
        state = {"active": 0, "peak": 0}

        def lookup(ip: str) -> str | None:
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            time.sleep(0.15)  # far above the timeout below
            with lock:
                state["active"] -= 1
            return f"{ip}.example.net"

        ips = [f"10.0.0.{n}" for n in range(1, 7)]
        async with HostnameResolver(timeout=0.02, concurrency=2, lookup=lookup) as resolver:
            result = await resolver.resolve(ips)
            await asyncio.sleep(0.4)  # let abandoned lookups finish

        self.assertEqual(result, {})
        self.assertLessEqual(state["peak"], 2)


class HostnameResolverTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_timeout_counts_from_the_start_of_a_lookup_not_from_queueing(self) -> None:
        def lookup(ip: str) -> str | None:
            time.sleep(0.3 if ip == "10.0.0.1" else 0.01)
            return f"{ip}.example.net"

        async with HostnameResolver(timeout=0.1, concurrency=1, lookup=lookup) as resolver:
            result = await resolver.resolve(["10.0.0.1", "10.0.0.2", "10.0.0.3"])

        # Only the stuck lookup is lost; the others wait for the free slot, then run in time.
        self.assertEqual(
            result, {"10.0.0.2": "10.0.0.2.example.net", "10.0.0.3": "10.0.0.3.example.net"}
        )


class HostnameResolverConfigTests(unittest.TestCase):
    def test_invalid_limits_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "concurrency"):
            HostnameResolver(timeout=1.0, concurrency=0)
        with self.assertRaisesRegex(ValueError, "timeout"):
            HostnameResolver(timeout=0, concurrency=1)


if __name__ == "__main__":
    unittest.main()

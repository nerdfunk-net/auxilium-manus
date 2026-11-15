import asyncio
import socket
import threading
import time
import unittest

from manus_agent.reverse_dns import DEFAULT_CONCURRENCY, resolve_names


class ResolveNamesTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_each_address_to_its_name_or_none(self) -> None:
        def lookup(ip: str) -> str:
            if ip == "10.0.0.2":
                raise socket.herror(1, "Unknown host")
            return f"host-{ip.rsplit('.', 1)[1]}.example.net"

        names = await resolve_names(["10.0.0.1", "10.0.0.2"], timeout=1, lookup=lookup)
        assert names == {"10.0.0.1": "host-1.example.net", "10.0.0.2": None}

    async def test_a_slow_lookup_times_out_without_failing_the_others(self) -> None:
        release = threading.Event()

        def lookup(ip: str) -> str:
            if ip == "10.0.0.2":
                release.wait(5)
            return "ok.example.net"

        started = time.monotonic()
        try:
            names = await resolve_names(["10.0.0.1", "10.0.0.2"], timeout=0.2, lookup=lookup)
        finally:
            release.set()
        assert names == {"10.0.0.1": "ok.example.net", "10.0.0.2": None}
        assert time.monotonic() - started < 2

    async def test_unexpected_lookup_errors_become_none(self) -> None:
        def lookup(ip: str) -> str:
            raise UnicodeError("bad")

        assert await resolve_names(["10.0.0.1"], timeout=1, lookup=lookup) == {"10.0.0.1": None}

    async def test_concurrency_is_bounded(self) -> None:
        active = 0
        peak = 0
        lock = threading.Lock()

        def lookup(ip: str) -> str:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return "n"

        hosts = [f"10.0.0.{i}" for i in range(1, 41)]
        await resolve_names(hosts, timeout=2, lookup=lookup, concurrency=4)
        assert 1 <= peak <= 4

    async def test_no_addresses_no_work(self) -> None:
        assert await resolve_names([], timeout=1) == {}

    async def test_the_name_is_trimmed_and_empty_means_none(self) -> None:
        names = await resolve_names(["10.0.0.1"], timeout=1, lookup=lambda ip: "  ")
        assert names == {"10.0.0.1": None}
        assert asyncio.get_running_loop().is_running()


class BudgetAndPoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_whole_lookup_phase_has_a_budget(self) -> None:
        release = threading.Event()

        def lookup(ip: str) -> str:
            release.wait(5)
            return "late"

        started = time.monotonic()
        try:
            names = await resolve_names(
                [f"10.0.0.{i}" for i in range(1, 30)],
                timeout=5,
                budget=0.3,
                lookup=lookup,
                concurrency=4,
            )
        finally:
            release.set()
        assert time.monotonic() - started < 2
        assert set(names.values()) == {None} and len(names) == 29

    async def test_stuck_lookups_do_not_pile_up_threads_across_calls(self) -> None:
        release = threading.Event()
        seen: set[str] = set()

        def lookup(ip: str) -> str:
            seen.add(threading.current_thread().name)
            release.wait(5)
            return "x"

        try:
            for _ in range(6):
                await resolve_names(
                    [f"10.0.0.{i}" for i in range(1, 20)], timeout=0.05, lookup=lookup
                )
        finally:
            release.set()
        # One shared pool: stuck calls cannot create more than its fixed number of threads.
        assert len(seen) <= DEFAULT_CONCURRENCY

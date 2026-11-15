import ipaddress
import socket
import unittest
from unittest.mock import AsyncMock

from manus_agent.hostpolicy import (
    SafeResolver,
    address_blocked,
    host_blocked,
    usable_device_name,
)


def ip(text: str):
    return ipaddress.ip_address(text)


class AddressTests(unittest.TestCase):
    def test_blocked_addresses(self) -> None:
        for text in ("169.254.169.254", "0.0.0.0", "224.0.0.1", "fe80::1", "::", "ff02::1"):
            with self.subTest(address=text):
                assert address_blocked(ip(text), loopback=False)

    def test_ipv4_mapped_ipv6_is_unwrapped(self) -> None:
        assert address_blocked(ip("::ffff:169.254.169.254"), loopback=False)
        assert address_blocked(ip("::ffff:127.0.0.1"), loopback=True)
        assert not address_blocked(ip("::ffff:10.0.0.1"), loopback=True)

    def test_loopback_depends_on_the_caller(self) -> None:
        assert not address_blocked(ip("127.0.0.1"), loopback=False)
        assert not address_blocked(ip("::1"), loopback=False)
        assert address_blocked(ip("127.0.0.1"), loopback=True)

    def test_ordinary_addresses_are_allowed(self) -> None:
        for text in ("10.0.0.1", "192.168.1.1", "8.8.8.8", "2001:db8::1"):
            assert not address_blocked(ip(text), loopback=True)


class HostTests(unittest.TestCase):
    def test_names_and_literals(self) -> None:
        assert host_blocked("metadata.google.internal", loopback_blocked=False)
        assert host_blocked("Metadata.Google.Com.", loopback_blocked=False)
        assert host_blocked("[fe80::1]", loopback_blocked=False)
        assert host_blocked("127.0.0.1", loopback_blocked=True)
        assert not host_blocked("127.0.0.1", loopback_blocked=False)
        assert not host_blocked("nautobot", loopback_blocked=True)


class DeviceNameTests(unittest.TestCase):
    def test_usable_names(self) -> None:
        for name in ("router1", "sw-01.example.net", "a_b.example.net", "10-0-0-1.lan", "A1"):
            with self.subTest(name=name):
                assert usable_device_name(name)

    def test_unusable_names(self) -> None:
        for name in (
            "",
            " ",
            "bad name",
            "line\nbreak",
            "tab\there",
            "-leading.example",
            "trailing-",
            "x" * 254,
            "metadata.google.internal",
            "127.0.0.1",
            "0.0.0.0",
            "169.254.169.254",
            "224.0.0.1",
            "a/b",
            "näme.example",
        ):
            with self.subTest(name=name):
                assert not usable_device_name(name)


class SafeResolverTests(unittest.IsolatedAsyncioTestCase):
    def resolver(self, *addresses: str) -> SafeResolver:
        resolver = SafeResolver()
        resolver._inner.resolve = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                {"hostname": "nb", "host": a, "port": 80, "family": 2, "proto": 6, "flags": 0}
                for a in addresses
            ]
        )
        resolver._inner.close = AsyncMock()  # type: ignore[method-assign]
        return resolver

    async def test_allowed_addresses_pass_and_blocked_ones_are_dropped(self) -> None:
        found = await self.resolver("169.254.169.254", "10.0.0.5").resolve("nb", 80, socket.AF_INET)
        assert [entry["host"] for entry in found] == ["10.0.0.5"]

    async def test_loopback_is_allowed(self) -> None:
        found = await self.resolver("127.0.0.1").resolve("nb", 80)
        assert [entry["host"] for entry in found] == ["127.0.0.1"]

    async def test_only_blocked_addresses_fail(self) -> None:
        with self.assertRaisesRegex(OSError, "link-local"):
            await self.resolver("169.254.169.254", "::ffff:169.254.169.254").resolve("nb", 80)

    async def test_close_closes_the_inner_resolver(self) -> None:
        resolver = self.resolver("10.0.0.5")
        await resolver.close()
        resolver._inner.close.assert_awaited_once()

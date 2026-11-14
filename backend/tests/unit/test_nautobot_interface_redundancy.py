"""Redundancy-group (HSRP/VRRP) writes of the interface workflow: naming, reuse, associations."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qsl, urlsplit

from services.nautobot.common.exceptions import NautobotAPIError
from services.nautobot.devices.interface_workflow import InterfaceManagerService
from services.nautobot.devices.interface_workflow.redundancy_naming import (
    next_free_name,
    validate_name_pattern,
)
from services.nautobot.devices.interface_workflow.state import InterfaceUpdateState

GROUPS = "dcim/interface-redundancy-groups/"
ASSOCS = "dcim/interface-redundancy-group-associations/"


class NamePatternTests(unittest.TestCase):
    def test_valid_and_invalid_patterns(self) -> None:
        self.assertIsNone(validate_name_pattern("hsrp-{next}"))
        self.assertIsNone(validate_name_pattern("{protocol}-grp-{next}"))
        for bad in (
            "hsrp",
            "hsrp-{next}-{next}",
            "a/{next}",
            "x-{next}-{foo}",
            "",
            "  ",
            "a{next}\n",
        ):
            with self.subTest(bad=bad):
                self.assertIsNotNone(validate_name_pattern(bad))

    def test_lowest_free_integer(self) -> None:
        self.assertEqual(next_free_name("hsrp-{next}", "hsrp", []), "hsrp-1")
        self.assertEqual(next_free_name("hsrp-{next}", "hsrp", ["hsrp-1", "hsrp-3"]), "hsrp-2")
        self.assertEqual(next_free_name("hsrp-{next}", "hsrp", ["hsrp-1", "hsrp-2"]), "hsrp-3")

    def test_other_names_are_ignored(self) -> None:
        names = ["hsrp-x", "HSRP-1", "hsrp-1-extra", "other-1", "hsrp-0"]
        self.assertEqual(next_free_name("hsrp-{next}", "hsrp", names), "hsrp-1")

    def test_protocol_placeholder_and_regex_chars_are_literal(self) -> None:
        self.assertEqual(
            next_free_name("{protocol}.grp-{next}", "vrrp", ["vrrp.grp-1"]), "vrrp.grp-2"
        )
        self.assertEqual(
            next_free_name("{protocol}.grp-{next}", "vrrp", ["vrrpXgrp-1"]), "vrrp.grp-1"
        )


class FakeNautobot:
    """Minimal in-memory Nautobot for the two redundancy endpoints."""

    def __init__(self) -> None:
        self.groups: list[dict[str, Any]] = []
        self.assocs: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str, Any]] = []

    async def rest_request(
        self, endpoint: str, method: str = "GET", data: Any = None
    ) -> dict[str, Any]:
        self.calls.append((method, endpoint, data))
        parts = urlsplit(endpoint)
        query = dict(parse_qsl(parts.query))
        if parts.path == GROUPS and method == "GET":
            rows = [g for g in self.groups if self._match_group(g, query)]
            return {"results": rows, "next": None}
        if parts.path == GROUPS and method == "POST":
            if any(g["name"] == data["name"] for g in self.groups):
                raise NautobotAPIError("name exists", http_status=400, fields=("name",))
            row = {"id": f"grp-{len(self.groups) + 1}", **data}
            self.groups.append(row)
            return row
        if parts.path == ASSOCS and method == "GET":
            rows = [
                a
                for a in self.assocs
                if a["interface"]["id"] == query["interface"]
                and a["interface_redundancy_group"]["id"] == query["interface_redundancy_group"]
            ]
            return {"results": rows, "next": None}
        if parts.path == ASSOCS and method == "POST":
            row = {"id": f"assoc-{len(self.assocs) + 1}", **data}
            self.assocs.append(row)
            return row
        if parts.path.startswith(ASSOCS) and method == "PATCH":
            assoc_id = parts.path[len(ASSOCS) :].strip("/")
            row = next(a for a in self.assocs if a["id"] == assoc_id)
            row.update(data)
            return row
        raise AssertionError(f"unexpected call {method} {endpoint}")

    @staticmethod
    def _match_group(group: dict[str, Any], query: dict[str, str]) -> bool:
        vip = group.get("virtual_ip") or {}
        checks = (
            ("protocol", group.get("protocol")),
            ("protocol_group_id", group.get("protocol_group_id")),
            ("virtual_ip", vip.get("id")),
        )
        if any(key in query and query[key] != value for key, value in checks):
            return False
        prefix = query.get("name__isw")
        return not prefix or group["name"].startswith(prefix)


def _service(fake: FakeNautobot) -> InterfaceManagerService:
    svc = InterfaceManagerService(fake)  # type: ignore[arg-type]
    svc.common = MagicMock()
    svc.common.resolve_namespace_id = AsyncMock(return_value="ns-1")
    svc.common.resolve_status_id = AsyncMock(return_value="status-active")
    svc.common.ensure_ip_address_exists = AsyncMock(
        side_effect=lambda **kw: f"ip:{kw['ip_address']}"
    )
    return svc


def _group(
    protocol: str = "hsrp",
    group_id: str = "0",
    vip: str = "192.168.180.100/24",
    priority: int | None = 110,
    name: str = "HSRP-1",
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "description": name,
        "protocol": protocol,
        "protocol_group_id": group_id,
        "virtual_ip": {"address": vip},
    }
    if priority is not None:
        entry["priority"] = priority
    return entry


def _state(**ids: str) -> InterfaceUpdateState:
    state = InterfaceUpdateState()
    state.interface_id_map.update(ids)
    return state


async def _apply(
    svc: InterfaceManagerService,
    interfaces: list[dict[str, Any]],
    state: InterfaceUpdateState,
    pattern: str | None = "hsrp-{next}",
) -> None:
    await svc._apply_redundancy_groups(
        interfaces=interfaces,
        state=state,
        name_pattern=pattern,
        group_status="Active",
        add_prefixes_automatically=False,
    )


class ApplyRedundancyGroupsTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_group_with_schema_name_and_association(self) -> None:
        fake = FakeNautobot()
        state = _state(Vlan200="if-200")
        await _apply(
            _service(fake),
            [{"name": "Vlan200", "interface_redundancy_groups": [_group()]}],
            state,
        )
        self.assertEqual(len(fake.groups), 1)
        group = fake.groups[0]
        self.assertEqual(group["name"], "hsrp-1")
        self.assertEqual(group["protocol"], "hsrp")
        self.assertEqual(group["protocol_group_id"], "0")
        self.assertEqual(group["virtual_ip"], {"id": "ip:192.168.180.100/24"})
        self.assertEqual(group["status"], {"id": "status-active"})
        self.assertEqual(group["description"], "HSRP-1")
        self.assertEqual(
            fake.assocs[0]["interface"],
            {"id": "if-200"},
        )
        self.assertEqual(fake.assocs[0]["interface_redundancy_group"], {"id": "grp-1"})
        self.assertEqual(fake.assocs[0]["priority"], 110)
        self.assertEqual(state.failed_interfaces, [])

    async def test_vip_ip_is_not_assigned_to_the_interface(self) -> None:
        fake = FakeNautobot()
        svc = _service(fake)
        await _apply(
            svc,
            [{"name": "Vlan200", "interface_redundancy_groups": [_group()]}],
            _state(Vlan200="if-200"),
        )
        self.assertFalse(any("ip-address-to-interface" in c[1] for c in fake.calls))
        svc.common.ensure_ip_address_exists.assert_awaited_once()

    async def test_default_priority_is_100(self) -> None:
        fake = FakeNautobot()
        await _apply(
            _service(fake),
            [{"name": "Vlan200", "interface_redundancy_groups": [_group(priority=None)]}],
            _state(Vlan200="if-200"),
        )
        self.assertEqual(fake.assocs[0]["priority"], 100)

    async def test_peer_device_reuses_the_group(self) -> None:
        fake = FakeNautobot()
        svc = _service(fake)
        iface = [{"name": "Vlan200", "interface_redundancy_groups": [_group(priority=110)]}]
        await _apply(svc, iface, _state(Vlan200="if-a"))
        peer = [{"name": "Vlan200", "interface_redundancy_groups": [_group(priority=90)]}]
        await _apply(svc, peer, _state(Vlan200="if-b"))
        self.assertEqual(len(fake.groups), 1)
        self.assertEqual([a["priority"] for a in fake.assocs], [110, 90])

    async def test_rerun_is_idempotent_and_patches_priority(self) -> None:
        fake = FakeNautobot()
        svc = _service(fake)
        await _apply(
            svc,
            [{"name": "Vlan200", "interface_redundancy_groups": [_group(priority=110)]}],
            _state(Vlan200="if-a"),
        )
        fake.calls.clear()
        await _apply(
            svc,
            [{"name": "Vlan200", "interface_redundancy_groups": [_group(priority=120)]}],
            _state(Vlan200="if-a"),
        )
        self.assertEqual(len(fake.groups), 1)
        self.assertEqual(len(fake.assocs), 1)
        self.assertEqual(fake.assocs[0]["priority"], 120)
        self.assertFalse(any(m == "POST" for m, _, _ in fake.calls))

    async def test_same_priority_makes_no_write(self) -> None:
        fake = FakeNautobot()
        svc = _service(fake)
        iface = [{"name": "Vlan200", "interface_redundancy_groups": [_group(priority=110)]}]
        await _apply(svc, iface, _state(Vlan200="if-a"))
        fake.calls.clear()
        await _apply(svc, iface, _state(Vlan200="if-a"))
        self.assertEqual([c for c in fake.calls if c[0] != "GET"], [])

    async def test_next_counter_skips_taken_names(self) -> None:
        fake = FakeNautobot()
        fake.groups = [
            {"id": "x1", "name": "hsrp-1", "protocol": "vrrp", "protocol_group_id": "9"},
            {"id": "x3", "name": "hsrp-3", "protocol": "vrrp", "protocol_group_id": "9"},
        ]
        await _apply(
            _service(fake),
            [{"name": "Vlan200", "interface_redundancy_groups": [_group()]}],
            _state(Vlan200="if-200"),
        )
        self.assertEqual(fake.groups[-1]["name"], "hsrp-2")

    async def test_two_groups_get_consecutive_names(self) -> None:
        fake = FakeNautobot()
        await _apply(
            _service(fake),
            [
                {"name": "Vlan10", "interface_redundancy_groups": [_group(vip="10.0.10.1/24")]},
                {"name": "Vlan20", "interface_redundancy_groups": [_group(vip="10.0.20.1/24")]},
            ],
            _state(Vlan10="if-10", Vlan20="if-20"),
        )
        self.assertEqual([g["name"] for g in fake.groups], ["hsrp-1", "hsrp-2"])

    async def test_name_conflict_recomputes_once(self) -> None:
        fake = FakeNautobot()
        real_post = fake.rest_request
        raced = {"done": False}

        async def racy(endpoint: str, method: str = "GET", data: Any = None) -> Any:
            if method == "POST" and endpoint == GROUPS and not raced["done"]:
                raced["done"] = True
                fake.groups.append(
                    {"id": "other", "name": "hsrp-1", "protocol": "hsrp", "protocol_group_id": "5"}
                )
            return await real_post(endpoint, method, data)

        fake.rest_request = racy  # type: ignore[method-assign]
        state = _state(Vlan200="if-200")
        await _apply(
            _service(fake),
            [{"name": "Vlan200", "interface_redundancy_groups": [_group()]}],
            state,
        )
        self.assertEqual(sorted(g["name"] for g in fake.groups), ["hsrp-1", "hsrp-2"])
        self.assertEqual(state.failed_interfaces, [])

    async def test_feature_off_makes_no_calls(self) -> None:
        fake = FakeNautobot()
        await _apply(
            _service(fake),
            [{"name": "Vlan200", "interface_redundancy_groups": [_group()]}],
            _state(Vlan200="if-200"),
            pattern=None,
        )
        self.assertEqual(fake.calls, [])

    async def test_interface_that_failed_earlier_is_skipped(self) -> None:
        fake = FakeNautobot()
        await _apply(
            _service(fake),
            [{"name": "Vlan200", "interface_redundancy_groups": [_group()]}],
            _state(),
        )
        self.assertEqual(fake.groups, [])

    async def test_failure_is_counted_and_reported(self) -> None:
        fake = FakeNautobot()
        svc = _service(fake)
        svc.common.ensure_ip_address_exists = AsyncMock(side_effect=RuntimeError("no prefix"))
        state = _state(Vlan200="if-200")
        await _apply(
            svc,
            [{"name": "Vlan200", "interface_redundancy_groups": [_group()]}],
            state,
        )
        self.assertEqual(state.failed_interfaces, ["Vlan200"])
        self.assertTrue(any("Vlan200" in w and "no prefix" in w for w in state.warnings))

    async def test_interface_without_groups_is_ignored(self) -> None:
        fake = FakeNautobot()
        await _apply(_service(fake), [{"name": "Vlan200"}], _state(Vlan200="if-200"))
        self.assertEqual(fake.calls, [])


class ReviewFixTests(unittest.IsolatedAsyncioTestCase):
    async def test_priority_missing_in_bag_never_patches_an_existing_association(self) -> None:
        fake = FakeNautobot()
        svc = _service(fake)
        await _apply(
            svc,
            [{"name": "Vlan200", "interface_redundancy_groups": [_group(priority=120)]}],
            _state(Vlan200="if-a"),
        )
        fake.calls.clear()
        await _apply(
            svc,
            [{"name": "Vlan200", "interface_redundancy_groups": [_group(priority=None)]}],
            _state(Vlan200="if-a"),
        )
        self.assertEqual(fake.assocs[0]["priority"], 120)
        self.assertEqual([c for c in fake.calls if c[0] != "GET"], [])

    async def test_virtual_ip_creation_is_serialized_between_peers(self) -> None:
        fake = FakeNautobot()
        svc = _service(fake)
        running = {"now": 0, "max": 0}
        created: set[str] = set()

        async def ensure(**kw: Any) -> str:
            running["now"] += 1
            running["max"] = max(running["max"], running["now"])
            await asyncio.sleep(0)
            created.add(kw["ip_address"])
            running["now"] -= 1
            return f"ip:{kw['ip_address']}"

        svc.common.ensure_ip_address_exists = AsyncMock(side_effect=ensure)
        iface = [{"name": "Vlan200", "interface_redundancy_groups": [_group()]}]
        await asyncio.gather(
            _apply(svc, iface, _state(Vlan200="if-a")),
            _apply(svc, iface, _state(Vlan200="if-b")),
        )
        self.assertEqual(running["max"], 1)
        self.assertEqual(len(fake.groups), 1)
        self.assertEqual(len(fake.assocs), 2)

    async def test_duplicate_ip_error_from_another_worker_is_retried(self) -> None:
        fake = FakeNautobot()
        svc = _service(fake)
        calls = {"n": 0}

        async def ensure(**kw: Any) -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                raise NautobotAPIError(
                    "IP address with this Parent and Host already exists", http_status=400
                )
            return f"ip:{kw['ip_address']}"

        svc.common.ensure_ip_address_exists = AsyncMock(side_effect=ensure)
        state = _state(Vlan200="if-a")
        await _apply(
            svc, [{"name": "Vlan200", "interface_redundancy_groups": [_group()]}], state
        )
        self.assertEqual(state.failed_interfaces, [])
        self.assertEqual(len(fake.assocs), 1)

    async def test_bare_virtual_ip_uses_the_unique_existing_address(self) -> None:
        fake = FakeNautobot()
        svc = _service(fake)
        real = fake.rest_request

        async def with_ips(endpoint: str, method: str = "GET", data: Any = None) -> Any:
            if endpoint.startswith("ipam/ip-addresses/"):
                return {"results": [{"id": "ip-existing", "address": "172.16.0.1/28"}]}
            return await real(endpoint, method, data)

        fake.rest_request = with_ips  # type: ignore[method-assign]
        await _apply(
            svc,
            [{"name": "Vlan200", "interface_redundancy_groups": [_group(vip="172.16.0.1")]}],
            _state(Vlan200="if-a"),
        )
        self.assertEqual(fake.groups[0]["virtual_ip"], {"id": "ip-existing"})
        svc.common.ensure_ip_address_exists.assert_not_awaited()

    async def test_bare_virtual_ip_without_a_known_address_fails_the_group(self) -> None:
        fake = FakeNautobot()
        svc = _service(fake)
        real = fake.rest_request

        async def no_ips(endpoint: str, method: str = "GET", data: Any = None) -> Any:
            if endpoint.startswith("ipam/ip-addresses/"):
                return {"results": []}
            return await real(endpoint, method, data)

        fake.rest_request = no_ips  # type: ignore[method-assign]
        state = _state(Vlan200="if-a")
        await _apply(
            svc,
            [{"name": "Vlan200", "interface_redundancy_groups": [_group(vip="172.16.0.1")]}],
            state,
        )
        self.assertEqual(state.failed_interfaces, ["Vlan200"])
        self.assertTrue(any("prefix length" in w for w in state.warnings))
        svc.common.ensure_ip_address_exists.assert_not_awaited()
        self.assertEqual(fake.groups, [])

    async def test_virtual_ip_namespace_is_used(self) -> None:
        fake = FakeNautobot()
        svc = _service(fake)
        group = {**_group(), "namespace": "black"}
        await _apply(
            svc,
            [{"name": "Vlan200", "interface_redundancy_groups": [group]}],
            _state(Vlan200="if-a"),
        )
        svc.common.resolve_namespace_id.assert_awaited_with("black")

    async def test_identity_conflict_reuses_the_group_the_other_worker_created(self) -> None:
        fake = FakeNautobot()
        real = fake.rest_request
        raced = {"done": False}

        async def racy(endpoint: str, method: str = "GET", data: Any = None) -> Any:
            if method == "POST" and endpoint == GROUPS and not raced["done"]:
                raced["done"] = True
                fake.groups.append(
                    {
                        "id": "peer-group",
                        "name": "hsrp-1",
                        "protocol": "hsrp",
                        "protocol_group_id": "0",
                        "virtual_ip": {"id": "ip:192.168.180.100/24"},
                    }
                )
                raise NautobotAPIError("already exists", http_status=400, fields=("__all__",))
            return await real(endpoint, method, data)

        fake.rest_request = racy  # type: ignore[method-assign]
        state = _state(Vlan200="if-a")
        await _apply(
            _service(fake),
            [{"name": "Vlan200", "interface_redundancy_groups": [_group()]}],
            state,
        )
        self.assertEqual(state.failed_interfaces, [])
        self.assertEqual([g["name"] for g in fake.groups], ["hsrp-1"])
        self.assertEqual(fake.assocs[0]["interface_redundancy_group"], {"id": "peer-group"})


if __name__ == "__main__":
    unittest.main()

"""Tests for AciDetailsService, driven by real payloads captured from the DevNet APIC (6.1(4h)).

``fixtures/aci_details_sandbox.json`` holds trimmed copies (a few real rows per class). The fake
client serves them per class and records every query, so the tests can also check what was asked.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from services.aci.common.exceptions import AciAPIError, AciNotFoundError, AciValidationError
from services.aci.credentials import AciCredentials
from services.aci.details_service import AciDetailsService, parse_uptime_seconds

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "aci_details_sandbox.json").read_text())
LEAF = FIXTURE["leaf101"]
SPINE = FIXTURE["spine201"]
CREDS = AciCredentials(base_url="https://10.10.20.14", username="admin", password="pw")


def _rows(section: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [dict(row) for row in section[name]["rows"]]


class FakeClient:
    """Serves rows per class name; ``errors`` raises for a class; records every call."""

    def __init__(
        self,
        data: dict[str, list[dict[str, Any]]],
        mo: dict[str, dict[str, Any] | None] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.data = data
        self.mo = mo or {}
        self.errors = errors or {}
        self.calls: list[tuple] = []

    async def query_node_class(self, credentials, pod_id, node_id, class_name, **kwargs):
        self.calls.append(("class", pod_id, node_id, class_name, kwargs))
        if class_name in self.errors:
            raise self.errors[class_name]
        return [dict(row) for row in self.data.get(class_name, [])]

    async def get_node_mo(self, credentials, pod_id, node_id, relative_dn, class_name):
        self.calls.append(("mo", pod_id, node_id, relative_dn, class_name))
        if relative_dn in self.errors:
            raise self.errors[relative_dn]
        return self.mo.get(relative_dn)

    def classes(self) -> list[str]:
        return [c[3] for c in self.calls if c[0] == "class"]


def leaf_client(**overrides: Any) -> FakeClient:
    data = {
        name: _rows(LEAF, name)
        for name in LEAF
        if name not in ("topSystem", "health_sys", "health_ch")
    }
    data["faultInst"] = _rows(LEAF, "faultInst_fabric_sample")
    data.update(overrides.pop("data", {}))
    mo: dict[str, dict[str, Any] | None] = {
        "sys": _rows(LEAF, "topSystem")[0],
        "": _rows(LEAF, "fabricNode")[0],
        "sys/health": _rows(LEAF, "health_sys")[0],
        "sys/ch/health": _rows(LEAF, "health_ch")[0],
    }
    mo.update(overrides.pop("mo", {}))
    return FakeClient(data, mo, **overrides)


def service(client: FakeClient) -> AciDetailsService:
    return AciDetailsService(client, CREDS)  # type: ignore[arg-type]


class UptimeTests(unittest.TestCase):
    def test_parses_the_apic_uptime_format(self) -> None:
        self.assertEqual(parse_uptime_seconds("00:07:18:38.000"), 7 * 3600 + 18 * 60 + 38)
        self.assertEqual(parse_uptime_seconds("12:00:00:01.500"), 12 * 86400 + 1)
        self.assertEqual(parse_uptime_seconds("00:07:18:38"), 26318)  # no fraction is fine

    def test_anything_else_is_none(self) -> None:
        for value in (None, "", "garbage", "1:2:3", "aa:bb:cc:dd.000", "00:07:18"):
            self.assertIsNone(parse_uptime_seconds(value), msg=repr(value))


class DeviceAndSoftwareTests(unittest.IsolatedAsyncioTestCase):
    async def test_device_facts_of_the_sandbox_leaf(self) -> None:
        client = leaf_client()
        device, _ = await service(client).get_device_and_software(1, 101)
        self.assertEqual(device.node_id, 101)
        self.assertEqual(device.pod_id, 1)
        self.assertEqual(device.name, "leaf-1")
        self.assertEqual(device.role, "leaf")
        self.assertEqual(device.model, "N9K-C9396PX")
        self.assertEqual(device.serial_number, "TEP-1-101")
        self.assertEqual(device.fabric_state, "active")
        self.assertEqual(device.system_state, "in-service")
        self.assertEqual(device.system_uptime, "00:07:25:12.000")
        self.assertEqual(device.system_uptime_seconds, 7 * 3600 + 25 * 60 + 12)
        self.assertEqual(device.last_reboot_time, "2026-11-06T10:58:26.833+00:00")
        self.assertEqual(device.tep_address, "10.0.64.64")
        self.assertEqual(device.fabric_mac, "00:22:BD:F8:19:FF")
        self.assertEqual(device.fabric_domain, "ACI Fabric1")
        self.assertEqual(device.control_plane_mtu, 9000)

    async def test_the_sandbox_switch_has_no_management_ip_and_the_tep_is_never_one(self) -> None:
        device, _ = await service(leaf_client()).get_device_and_software(1, 101)
        self.assertIsNone(device.management_ip)
        self.assertIsNone(device.oob_ip)
        self.assertIsNone(device.inb_ip)
        self.assertEqual(device.tep_address, "10.0.64.64")

    async def test_oob_is_preferred_over_inband(self) -> None:
        sys_row = {
            **_rows(LEAF, "topSystem")[0],
            "oobMgmtAddr": "10.1.1.5",
            "inbMgmtAddr": "192.168.1.5",
        }
        device, _ = await service(leaf_client(mo={"sys": sys_row})).get_device_and_software(1, 101)
        self.assertEqual(
            (device.management_ip, device.oob_ip, device.inb_ip),
            ("10.1.1.5", "10.1.1.5", "192.168.1.5"),
        )

    async def test_software_facts(self) -> None:
        _, software = await service(leaf_client()).get_device_and_software(1, 101)
        self.assertEqual(software.software_version, "simsw-6.1(4h)")
        self.assertEqual(software.system_version, "simsw-6.1(4h)")
        self.assertEqual(software.image_type, _rows(LEAF, "firmwareRunning")[0]["type"] or None)

    async def test_the_running_switch_image_wins_over_other_firmware_rows(self) -> None:
        rows = [
            {"type": "controller", "version": "apic-9.9"},
            {"type": "switch", "version": "n9000-16.0(4h)"},
        ]
        _, software = await service(
            leaf_client(data={"firmwareRunning": rows})
        ).get_device_and_software(1, 101)
        self.assertEqual(
            (software.software_version, software.image_type), ("n9000-16.0(4h)", "switch")
        )

    async def test_without_a_switch_image_the_system_version_is_used(self) -> None:
        rows = [{"type": "controller", "version": "apic-9.9"}]
        _, software = await service(
            leaf_client(data={"firmwareRunning": rows})
        ).get_device_and_software(1, 101)
        self.assertEqual(software.software_version, "simsw-6.1(4h)")

    async def test_asks_for_the_right_objects_once_each(self) -> None:
        client = leaf_client()
        await service(client).get_device_and_software(1, 101)
        self.assertEqual(client.classes(), ["firmwareRunning"])
        self.assertEqual(
            sorted(c[3:] for c in client.calls if c[0] == "mo"),
            [("", "fabricNode"), ("sys", "topSystem")],
        )

    async def test_a_missing_system_object_is_not_found(self) -> None:
        with self.assertRaises(AciNotFoundError):
            await service(leaf_client(mo={"sys": None})).get_device_and_software(1, 101)

    async def test_blank_values_become_none_and_a_bad_number_is_none(self) -> None:
        sys_row = {
            **_rows(LEAF, "topSystem")[0],
            "controlPlaneMTU": "x",
            "systemUpTime": "",
            "name": "",
        }
        device, _ = await service(leaf_client(mo={"sys": sys_row})).get_device_and_software(1, 101)
        self.assertIsNone(device.control_plane_mtu)
        self.assertIsNone(device.system_uptime_seconds)
        self.assertEqual(device.name, "leaf-1")  # falls back to fabricNode.name


class HardwareTests(unittest.IsolatedAsyncioTestCase):
    async def test_leaf_inventory_from_real_rows(self) -> None:
        items = await service(leaf_client()).get_hardware(1, 101)
        by_kind: dict[str, list] = {}
        for item in items:
            by_kind.setdefault(item.kind, []).append(item)
        self.assertEqual(
            {k: len(v) for k, v in by_kind.items()},
            {
                "chassis": 1,
                "supervisor": 1,
                "line_card": 1,
                "fan": 2,
                "power_supply": 2,
                "cpu": 2,
                "memory": 2,
            },
        )
        chassis = by_kind["chassis"][0]
        self.assertEqual(
            (chassis.model, chassis.serial_number, chassis.vendor, chassis.revision),
            ("N9K-C9396PX", "TEP-1-101", "Cisco Systems, Inc", "0.1.6"),
        )
        sup = by_kind["supervisor"][0]
        self.assertEqual(
            (sup.slot, sup.model, sup.serial_number, sup.revision),
            (5, "N9K-C9396PX", "FOX-377569", "1.0.3"),
        )
        self.assertEqual(
            (by_kind["line_card"][0].slot, by_kind["line_card"][0].model), (1, "N9K-M12PQ")
        )

    async def test_fans_and_psus_carry_slot_index_and_state(self) -> None:
        items = await service(leaf_client()).get_hardware(1, 101)
        fan = next(i for i in items if i.kind == "fan" and i.index == 8)
        self.assertEqual(
            (fan.slot, fan.index, fan.model, fan.serial_number, fan.state),
            (4, 8, "NXS8-0378", "FOX-380261", "ok"),
        )
        psus = sorted((i.slot, i.serial_number, i.state) for i in items if i.kind == "power_supply")
        self.assertEqual(psus, [(2, "FOX-448365", "ok"), (3, "FOX-770469", "ok")])

    async def test_cpu_and_memory_say_which_module_they_sit_on(self) -> None:
        items = await service(leaf_client()).get_hardware(1, 101)
        cpus = sorted((i.slot, i.index) for i in items if i.kind == "cpu")
        self.assertEqual(cpus, [(1, 1), (5, 1)])  # lc slot 1 and supervisor slot 5
        dimm = next(i for i in items if i.kind == "memory" and i.slot == 5)
        self.assertEqual((dimm.index, dimm.serial_number, dimm.state), (2, "FOX-744521", "ok"))

    async def test_spine_has_fabric_cards_and_a_system_controller(self) -> None:
        data = {name: _rows(SPINE, name) for name in SPINE}
        items = await service(FakeClient(data)).get_hardware(1, 201)
        kinds = sorted({i.kind for i in items})
        self.assertIn("system_controller", kinds)
        self.assertIn("fabric_card", kinds)
        self.assertIn("line_card", kinds)
        self.assertEqual(next(i for i in items if i.kind == "chassis").model, "N9K-C9508")
        self.assertEqual(next(i for i in items if i.kind == "system_controller").model, "N9K-SC-A")

    async def test_a_class_the_switch_does_not_have_is_skipped_but_other_errors_are_not(
        self,
    ) -> None:
        unresolved = AciValidationError(
            "Request failed, unresolved class for eqptFC", http_status=400
        )
        items = await service(
            leaf_client(errors={"eqptFC": unresolved, "eqptSysC": unresolved})
        ).get_hardware(1, 101)
        self.assertGreater(len(items), 5)
        with self.assertRaises(AciAPIError):
            await service(
                leaf_client(errors={"eqptCh": AciAPIError("down", http_status=503)})
            ).get_hardware(1, 101)

    async def test_rows_without_a_dn_slot_still_appear(self) -> None:
        row = {"model": "X", "ser": "S", "dn": "topology/pod-1/node-101/sys/ch"}
        items = await service(FakeClient({"eqptCh": [row]})).get_hardware(1, 101)
        self.assertEqual(
            [(i.kind, i.slot, i.model, i.serial_number) for i in items],
            [("chassis", None, "X", "S")],
        )


class InterfaceTests(unittest.IsolatedAsyncioTestCase):
    async def _by_name(self, client: FakeClient | None = None) -> dict[str, Any]:
        interfaces = await service(client or leaf_client()).get_interfaces(1, 101)
        return {i.name: i for i in interfaces}

    async def test_physical_interface_joins_config_and_operational_state(self) -> None:
        eth = (await self._by_name())["eth1/1"]
        self.assertEqual(eth.kind, "physical")
        self.assertEqual(
            (eth.admin_status, eth.oper_status, eth.oper_status_reason), ("up", "up", "link-up")
        )
        self.assertEqual((eth.layer, eth.mode, eth.mtu), ("Layer2", "trunk", 9000))
        self.assertEqual((eth.port_type, eth.usage), ("leaf", "discovery"))
        self.assertEqual(eth.duplex, "auto")

    async def test_inherit_unknown_and_empty_values_are_none(self) -> None:
        eth = (await self._by_name())["eth1/1"]
        self.assertIsNone(eth.speed)  # "inherit"
        self.assertIsNone(eth.oper_speed)  # "inherit"
        self.assertIsNone(eth.access_vlan)  # "unknown"
        self.assertIsNone(eth.native_vlan)  # "unknown"
        self.assertIsNone(eth.description)  # ""
        self.assertIsNone(eth.mac_address)  # 00:00:00:00:00:00

    async def test_down_and_fabric_facing_ports(self) -> None:
        by_name = await self._by_name()
        self.assertEqual(
            (
                by_name["eth1/32"].admin_status,
                by_name["eth1/32"].oper_status,
                by_name["eth1/32"].oper_status_reason,
            ),
            ("up", "down", "admin-down"),
        )
        uplink = by_name["eth1/49"]
        self.assertEqual(
            (uplink.layer, uplink.mtu, uplink.port_type, uplink.usage),
            ("Layer3", 9366, "fab", "fabric"),
        )

    async def test_a_description_a_real_speed_and_a_mac_are_kept(self) -> None:
        l1 = {**_rows(LEAF, "l1PhysIf")[0], "descr": "to server 12", "speed": "10G"}
        pm = {
            **_rows(LEAF, "ethpmPhysIf")[0],
            "operSpeed": "25G",
            "backplaneMac": "aa:bb:cc:00:11:22",
        }
        pm["dn"] = pm["dn"].replace(pm["dn"].split("phys-[")[1].split("]")[0], l1["id"])
        eth = (await self._by_name(leaf_client(data={"l1PhysIf": [l1], "ethpmPhysIf": [pm]})))[
            l1["id"]
        ]
        self.assertEqual(
            (eth.description, eth.speed, eth.oper_speed, eth.mac_address),
            ("to server 12", "10G", "25G", "AA:BB:CC:00:11:22"),
        )

    async def test_a_physical_interface_without_operational_data_is_still_listed(self) -> None:
        eth = (await self._by_name(leaf_client(data={"ethpmPhysIf": []})))["eth1/1"]
        self.assertEqual((eth.admin_status, eth.mtu), ("up", 9000))
        self.assertIsNone(eth.oper_status)

    async def test_port_channels_know_their_members_and_members_know_the_channel(self) -> None:
        member = {
            **_rows(LEAF, "l1PhysIf")[0],
            "id": "eth1/15",
            "dn": "topology/pod-1/node-101/sys/phys-[eth1/15]",
        }
        by_name = await self._by_name(leaf_client(data={"l1PhysIf": [member]}))
        po1 = by_name["po1"]
        self.assertEqual(
            (po1.kind, po1.mode, po1.layer, po1.mtu), ("port_channel", "trunk", "Layer2", 9000)
        )
        self.assertEqual(po1.members, ("eth1/13", "eth1/14", "eth1/15", "eth1/16"))
        self.assertEqual(by_name["eth1/15"].port_channel, "po1")

    async def test_management_loopback_and_svi_interfaces(self) -> None:
        by_name = await self._by_name()
        mgmt = by_name["mgmt0"]
        self.assertEqual(
            (mgmt.kind, mgmt.mtu, mgmt.speed, mgmt.admin_status), ("management", 9000, "1G", "up")
        )
        lo0 = by_name["lo0"]
        self.assertEqual((lo0.kind, lo0.admin_status), ("loopback", "up"))
        svi = by_name["vlan13"]
        self.assertEqual(
            (svi.kind, svi.mtu, svi.oper_status, svi.vlan_id, svi.mac_address),
            ("svi", 9216, "up", 13, "00:22:BD:F8:19:FF"),
        )

    async def test_addresses_are_joined_by_interface_and_carry_vrf_and_type(self) -> None:
        by_name = await self._by_name()
        self.assertEqual(
            [(a.address, a.type, a.vrf) for a in by_name["lo0"].ipv4_addresses],
            [("10.0.64.64/32", "primary", "overlay-1")],
        )
        self.assertEqual([a.address for a in by_name["vlan13"].ipv4_addresses], ["10.0.0.30/27"])
        vlan17 = sorted((a.address, a.vrf) for a in by_name["vlan17"].ipv4_addresses)
        self.assertEqual(
            vlan17,
            [("10.1.120.1/22", "Heroes:Heroes_Only"), ("192.168.120.1/22", "Heroes:Heroes_Only")],
        )

    async def test_a_routed_physical_port_gets_its_address(self) -> None:
        routed = {
            **_rows(LEAF, "l1PhysIf")[0],
            "id": "eth1/47",
            "dn": "topology/pod-1/node-101/sys/phys-[eth1/47]",
            "layer": "Layer3",
        }
        by_name = await self._by_name(leaf_client(data={"l1PhysIf": [routed]}))
        self.assertEqual(
            [(a.address, a.vrf) for a in by_name["eth1/47"].ipv4_addresses],
            [("10.1.200.1/31", "Heroes:Heroes_Only")],
        )

    async def test_order_is_numeric_and_grouped_by_kind(self) -> None:
        rows = []
        for port in ("eth1/10", "eth1/2", "eth1/1", "eth2/1"):
            rows.append(
                {
                    **_rows(LEAF, "l1PhysIf")[0],
                    "id": port,
                    "dn": f"topology/pod-1/node-101/sys/phys-[{port}]",
                }
            )
        names = [
            i.name
            for i in await service(leaf_client(data={"l1PhysIf": rows})).get_interfaces(1, 101)
        ]
        self.assertEqual(names[:4], ["eth1/1", "eth1/2", "eth1/10", "eth2/1"])
        kinds = [i.kind for i in await service(leaf_client()).get_interfaces(1, 101)]
        self.assertEqual(
            kinds,
            sorted(kinds, key=["physical", "port_channel", "management", "loopback", "svi"].index),
        )

    async def test_a_row_without_an_id_is_skipped(self) -> None:
        bad = {**_rows(LEAF, "l1PhysIf")[0], "id": ""}
        names = [
            i.name
            for i in await service(leaf_client(data={"l1PhysIf": [bad]})).get_interfaces(1, 101)
        ]
        self.assertNotIn("", names)

    async def test_an_error_in_the_main_class_fails_the_fact(self) -> None:
        with self.assertRaises(AciAPIError):
            await service(
                leaf_client(errors={"l1PhysIf": AciAPIError("down", http_status=503)})
            ).get_interfaces(1, 101)

    async def test_optional_classes_missing_do_not_fail_the_fact(self) -> None:
        gone = AciValidationError("unresolved class", http_status=400)
        interfaces = await service(
            leaf_client(errors={"pcAggrIf": gone, "sviIf": gone, "l3LbRtdIf": gone})
        ).get_interfaces(1, 101)
        self.assertTrue(any(i.kind == "physical" for i in interfaces))
        self.assertFalse(any(i.kind in ("port_channel", "svi", "loopback") for i in interfaces))

    async def test_other_errors_of_an_optional_class_propagate(self) -> None:
        for error in (
            AciValidationError("bad request", http_status=422),
            AciValidationError("Unable to process the query, dataset too big", http_status=400),
            AciValidationError("", http_status=400),
            AciValidationError("no status"),
            AciAPIError("down", http_status=503),
        ):
            with self.subTest(error=repr(error)):
                with self.assertRaises((AciAPIError, AciValidationError)):
                    await service(leaf_client(errors={"pcAggrIf": error})).get_interfaces(1, 101)

    async def test_the_row_limit_is_passed_to_the_client(self) -> None:
        client = leaf_client()
        await service(client).get_interfaces(1, 101)
        limits = {c[3]: c[4].get("max_objects") for c in client.calls if c[0] == "class"}
        self.assertEqual(limits["l1PhysIf"], 5000)


class NeighborTests(unittest.IsolatedAsyncioTestCase):
    async def test_lldp_neighbours_of_the_sandbox_leaf(self) -> None:
        neighbours = await service(leaf_client()).get_neighbors(1, 101)
        by_port = {n.local_port: n for n in neighbours}
        self.assertEqual(sorted(by_port), ["eth1/41", "eth1/49"])
        apic = by_port["eth1/41"]
        self.assertEqual(
            (apic.protocol, apic.remote_name, apic.remote_port, apic.remote_mgmt_ip),
            ("lldp", "apic1", "apic1-eth2", "10.0.0.1"),
        )
        self.assertEqual(apic.remote_chassis_id, "0a:f8:19:41:06:b7")
        spine = by_port["eth1/49"]
        self.assertEqual(
            (spine.remote_name, spine.remote_mgmt_ip, spine.capabilities),
            ("spine-1", "10.0.64.65", "router"),
        )
        self.assertEqual(spine.ttl, 120)

    async def test_no_cdp_neighbours_in_the_sandbox_is_not_an_error(self) -> None:
        self.assertEqual(len(await service(leaf_client()).get_neighbors(1, 101)), 2)

    async def test_cdp_neighbours_are_best_effort(self) -> None:
        row = {
            "dn": "topology/pod-1/node-101/sys/cdp/inst/if-[eth1/5]/adj-1",
            "devId": "sw9",
            "portId": "Ethernet1/9",
            "platId": "N9K-X",
            "ver": "9.3(1)",
            "mgmtIp": "10.9.9.9",
        }
        neighbours = await service(
            leaf_client(data={"cdpAdjEp": [row], "lldpAdjEp": []})
        ).get_neighbors(1, 101)
        self.assertEqual(
            [
                (
                    n.protocol,
                    n.local_port,
                    n.remote_name,
                    n.remote_port,
                    n.remote_model,
                    n.remote_mgmt_ip,
                )
                for n in neighbours
            ],
            [("cdp", "eth1/5", "sw9", "Ethernet1/9", "N9K-X", "10.9.9.9")],
        )

    async def test_a_zero_management_address_is_none(self) -> None:
        row = {**_rows(LEAF, "lldpAdjEp")[0], "mgmtIp": "0.0.0.0"}
        neighbours = await service(leaf_client(data={"lldpAdjEp": [row]})).get_neighbors(1, 101)
        self.assertIsNone(neighbours[0].remote_mgmt_ip)


class VlanTests(unittest.IsolatedAsyncioTestCase):
    async def test_vlans_with_epg_bridge_domain_and_vrf(self) -> None:
        vlans = await service(leaf_client()).get_vlans(1, 101)
        first = next(v for v in vlans if v.encap == "vlan-200")
        self.assertEqual(
            (first.vlan_id, first.encap_vlan, first.fabric_encap, first.state),
            (18, 200, "vxlan-8292", "down"),
        )
        self.assertEqual(
            (first.name, first.epg),
            ("Heroes:Save_The_Planet:web", "uni/tn-Heroes/ap-Save_The_Planet/epg-web"),
        )
        self.assertEqual(
            (first.bridge_domain, first.vrf), ("Heroes:Hero_Land", "Heroes:Heroes_Only")
        )

    async def test_a_vlan_on_an_unknown_bridge_domain_keeps_the_rest(self) -> None:
        vlans = await service(leaf_client(data={"l2BD": [], "l3Ctx": []})).get_vlans(1, 101)
        self.assertTrue(all(v.bridge_domain is None and v.vrf is None for v in vlans))
        self.assertEqual(len(vlans), 3)


class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_node_and_chassis_health(self) -> None:
        health = await service(leaf_client()).get_health(1, 101)
        self.assertEqual(
            (health.score, health.previous_score, health.change, health.max_severity),
            (90, 100, -10, "cleared"),
        )
        self.assertEqual((health.chassis_score, health.chassis_previous_score), (97, 98))

    async def test_missing_objects_give_none_scores(self) -> None:
        health = await service(
            leaf_client(mo={"sys/health": None, "sys/ch/health": None})
        ).get_health(1, 101)
        self.assertEqual((health.score, health.chassis_score), (None, None))

    async def test_one_missing_health_object_keeps_the_other_score(self) -> None:
        gone = AciNotFoundError("missing", http_status=404)
        health = await service(leaf_client(errors={"sys/ch/health": gone})).get_health(1, 101)
        self.assertEqual((health.score, health.chassis_score), (90, None))
        health = await service(leaf_client(errors={"sys/health": gone})).get_health(1, 101)
        self.assertEqual((health.score, health.chassis_score), (None, 97))

    async def test_a_failure_to_read_the_node_health_fails_the_fact(self) -> None:
        with self.assertRaises(AciAPIError):
            await service(
                leaf_client(errors={"sys/health": AciAPIError("down", http_status=503)})
            ).get_health(1, 101)


class FaultTests(unittest.IsolatedAsyncioTestCase):
    async def test_counts_and_items_of_real_faults(self) -> None:
        faults = await service(leaf_client()).get_faults(1, 101)
        self.assertEqual(
            (faults.total, faults.by_severity, faults.truncated),
            (2, {"critical": 1, "major": 1}, False),
        )
        self.assertEqual([f.severity for f in faults.items], ["critical", "major"])
        first = faults.items[0]
        self.assertEqual(
            (first.code, first.cause, first.lifecycle, first.type, first.acknowledged),
            ("F0104", "port-down", "raised", "operational", False),
        )

    async def test_the_query_is_scoped_to_the_node_by_a_validated_filter(self) -> None:
        client = leaf_client()
        await service(client).get_faults(2, 1101)
        call = next(c for c in client.calls if c[3] == "faultInst")
        self.assertEqual(call[4]["query_filter"], 'wcard(faultInst.dn,"topology/pod-2/node-1101/")')

    async def test_only_the_first_fifty_are_returned_but_all_are_counted(self) -> None:
        base = _rows(LEAF, "faultInst_fabric_sample")[1]
        rows = [
            {**base, "code": f"F{i:04d}", "severity": "warning" if i % 2 else "major"}
            for i in range(60)
        ]
        faults = await service(leaf_client(data={"faultInst": rows})).get_faults(1, 101)
        self.assertEqual((faults.total, len(faults.items), faults.truncated), (60, 50, True))
        self.assertEqual(faults.by_severity, {"major": 30, "warning": 30})
        self.assertEqual({f.severity for f in faults.items[:30]}, {"major"})  # worst first

    async def test_a_long_description_is_capped(self) -> None:
        row = {**_rows(LEAF, "faultInst_fabric_sample")[0], "descr": "x" * 1000}
        faults = await service(leaf_client(data={"faultInst": [row]})).get_faults(1, 101)
        self.assertEqual(len(faults.items[0].description or ""), 300)

    async def test_no_faults(self) -> None:
        faults = await service(leaf_client(data={"faultInst": []})).get_faults(1, 101)
        self.assertEqual(
            (faults.total, faults.by_severity, faults.items, faults.truncated), (0, {}, (), False)
        )


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_routes_with_their_next_hops(self) -> None:
        routes = await service(leaf_client()).get_routes(1, 101)
        by_key = {(r.vrf, r.prefix): r for r in routes}
        self.assertIn(("SnV:Superverse", "10.2.10.0/23"), by_key)
        self.assertEqual(by_key[("SnV:Superverse", "10.2.10.0/23")].preference, 1)
        routed = by_key[("Heroes:Heroes_Only", "192.168.120.0/22")]
        self.assertEqual(
            [(h.address, h.vrf, h.interface) for h in routed.next_hops],
            [("10.0.200.65/32", "overlay-1", None)],
        )

    async def test_next_hops_of_routes_not_listed_are_dropped(self) -> None:
        nh = {
            "nhAddr": "1.1.1.1/32",
            "nhIf": "eth1/1",
            "nhVrf": "v",
            "pref": "1",
            "dn": (
                "topology/pod-1/node-101/sys/ipv4/inst/dom-v/rt-[9.9.9.0/24]"
                "/nh-[eth1/1]-addr-[1.1.1.1/32]-vrf-[v]"
            ),
        }
        routes = await service(leaf_client(data={"ipv4Nexthop": [nh]})).get_routes(1, 101)
        self.assertTrue(all(not r.next_hops for r in routes))

    async def test_the_row_limit_applies(self) -> None:
        client = leaf_client()
        await service(client).get_routes(1, 101)
        limits = {c[3]: c[4].get("max_objects") for c in client.calls if c[0] == "class"}
        self.assertEqual((limits["ipv4Route"], limits["ipv4Nexthop"]), (20000, 100000))


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_bgp_peer(self) -> None:
        protocols = await service(leaf_client()).get_protocols(1, 101)
        self.assertEqual(
            [
                (p.vrf, p.address, p.asn, p.type, p.admin_state, p.oper_state)
                for p in protocols.bgp_peers
            ],
            [("MOJ_TENANT:MOJ_VRF", "10.115.100.4/32", "65555", "local", "enabled", None)],
        )
        self.assertEqual(protocols.adjacencies, ())

    async def test_adjacencies_keep_the_known_operational_fields(self) -> None:
        row = {
            "dn": (
                "topology/pod-1/node-101/sys/isis/inst-default/dom-overlay-1/if-[eth1/49.14]/adj-1"
            ),
            "operSt": "up",
            "sysId": "0000.0001.0001",
            "empty": "",
            "modTs": "2026-11-06",
        }
        protocols = await service(leaf_client(data={"isisAdjEp": [row]})).get_protocols(1, 101)
        adj = protocols.adjacencies[0]
        self.assertEqual((adj.protocol, adj.state), ("isis", "up"))
        self.assertEqual(adj.attributes["sysId"], "0000.0001.0001")
        self.assertNotIn("empty", adj.attributes)

    async def test_adjacencies_copy_only_known_operational_fields(self) -> None:
        row = {
            "dn": "topology/pod-1/node-101/sys/ospf/inst-default/dom-x/if-[eth1/1]/adj-1",
            "operSt": "full",
            "peerIp": "10.0.0.2",
            "authKey": "secret-key",
            "unknownField": "x",
        }
        protocols = await service(leaf_client(data={"ospfAdjEp": [row]})).get_protocols(1, 101)
        adj = protocols.adjacencies[0]
        self.assertNotIn("authKey", adj.attributes)
        self.assertNotIn("unknownField", adj.attributes)
        self.assertNotIn("secret-key", adj.model_dump_json())

    async def test_ospf_adjacencies_are_read_too(self) -> None:
        row = {
            "dn": "topology/pod-1/node-101/sys/ospf/inst-default/dom-x/if-[eth1/1]/adj-1",
            "operSt": "full",
        }
        protocols = await service(leaf_client(data={"ospfAdjEp": [row]})).get_protocols(1, 101)
        self.assertEqual([(a.protocol, a.state) for a in protocols.adjacencies], [("ospf", "full")])

    async def test_a_protocol_the_switch_does_not_run_is_empty_not_an_error(self) -> None:
        gone = AciValidationError("unresolved class", http_status=400)
        protocols = await service(
            leaf_client(errors={"isisAdjEp": gone, "ospfAdjEp": gone})
        ).get_protocols(1, 101)
        self.assertEqual(len(protocols.bgp_peers), 1)


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_learned_endpoints_with_vrf_and_vlan(self) -> None:
        endpoints = await service(leaf_client()).get_endpoints(1, 101)
        ips = [e for e in endpoints if e.kind == "ip"]
        macs = [e for e in endpoints if e.kind == "mac"]
        self.assertEqual((len(ips), len(macs)), (3, 3))
        first = next(e for e in ips if e.address == "2222::65:4")
        self.assertEqual(
            (first.interface, first.vrf, first.pc_tag), ("po4", "SnV:Superverse", "any")
        )
        mac = next(e for e in macs if e.address == "43:CD:BB:C0:00:00")
        self.assertEqual(
            (mac.interface, mac.encap_vlan, mac.flags, mac.vrf),
            ("po2", 200, "local", "Heroes:Heroes_Only"),
        )

    async def test_the_limit_fails_the_fact_instead_of_truncating(self) -> None:
        too_many = AciAPIError(
            "APIC class epmIpEp has more than 10000 objects", code="too_many_objects"
        )
        with self.assertRaises(AciAPIError):
            await service(leaf_client(errors={"epmIpEp": too_many})).get_endpoints(1, 101)
        client = leaf_client()
        await service(client).get_endpoints(1, 101)
        limits = {c[3]: c[4].get("max_objects") for c in client.calls if c[0] == "class"}
        self.assertEqual((limits["epmIpEp"], limits["epmMacEp"]), (10000, 10000))


class VpcTests(unittest.IsolatedAsyncioTestCase):
    async def test_vpc_domain_and_interfaces(self) -> None:
        vpc = await service(leaf_client()).get_vpc(1, 101)
        self.assertEqual(
            (vpc.domain_id, vpc.peer_state, vpc.peer_state_reason, vpc.peer_ip),
            ("12", "up", "uplinks-down", "10.0.64.66/32"),
        )
        self.assertEqual((vpc.role, vpc.virtual_ip), ("election-not-done", "10.0.200.64/32"))
        self.assertEqual([i.id for i in vpc.interfaces], ["1", "684", "685"])
        self.assertIsNone(vpc.interfaces[0].local_state)  # "unknown"

    async def test_a_switch_without_vpc_is_empty(self) -> None:
        vpc = await service(leaf_client(data={"vpcDom": [], "vpcIf": []})).get_vpc(1, 101)
        self.assertEqual((vpc.domain_id, vpc.interfaces), (None, ()))

    async def test_a_switch_that_has_no_vpc_class_is_empty(self) -> None:
        gone = AciValidationError("unresolved class", http_status=400)
        vpc = await service(leaf_client(errors={"vpcDom": gone, "vpcIf": gone})).get_vpc(1, 101)
        self.assertIsNone(vpc.domain_id)


class ImmutabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_facts_are_frozen(self) -> None:
        device, _ = await service(leaf_client()).get_device_and_software(1, 101)
        with self.assertRaises(Exception):  # noqa: B017 - pydantic ValidationError
            device.name = "x"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()

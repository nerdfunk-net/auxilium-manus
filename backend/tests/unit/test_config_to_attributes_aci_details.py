"""Tests for the config-to-attributes ``aci_details`` source format."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from models.aci_facts import AciDeviceDetails, AciInterface, AciInterfaceAddress, AciSoftware
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from workflow_steps.config_to_attributes.aci_details import (
    build_device_fields_from_aci_details,
    build_interfaces_from_aci_details,
)
from workflow_steps.config_to_attributes.executor import execute

_KEY = "aci_details"


def _iface(name: str, kind: str = "physical", **overrides: Any) -> dict[str, Any]:
    data = {"name": name, "kind": kind, "admin_status": "up", **overrides}
    if "ipv4_addresses" in data:
        data["ipv4_addresses"] = tuple(
            AciInterfaceAddress(**a) if isinstance(a, dict) else a for a in data["ipv4_addresses"]
        )
    return AciInterface(**data).model_dump(mode="json")


_DEVICE = AciDeviceDetails(
    node_id=101,
    pod_id=1,
    name="leaf-1",
    role="leaf",
    model="N9K-C9396PX",
    serial_number="TEP-1-101",
).model_dump(mode="json")
_SOFTWARE = AciSoftware(software_version="simsw-6.1(4h)", image_type="switch").model_dump(
    mode="json"
)


def _entry(
    *,
    interfaces: list[dict[str, Any]] | None = None,
    device: dict[str, Any] | None = None,
    software: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    if interfaces is not None:
        entry["interfaces"] = {"parsed": interfaces, "error": None}
    if device is not None:
        entry["device"] = {"parsed": device, "error": None}
    if software is not None:
        entry["software"] = {"parsed": software, "error": None}
    return entry


class BuildInterfacesTests(unittest.TestCase):
    def _one(self, iface: dict[str, Any]) -> dict[str, Any]:
        built = build_interfaces_from_aci_details(_entry(interfaces=[iface]))
        self.assertEqual(len(built), 1)
        return built[0]

    def test_a_physical_port_with_the_sandbox_values(self) -> None:
        iface = self._one(
            _iface(
                "eth1/1", oper_status="up", layer="Layer2", mode="trunk", mtu=9000, duplex="auto"
            )
        )
        self.assertEqual(
            (iface["name"], iface["status"], iface["enabled"]), ("eth1/1", "Active", True)
        )
        self.assertEqual(iface["mtu"], 9000)
        self.assertEqual(iface["type"], "other")  # speed "inherit": no honest guess
        # Nautobot refuses a duplex on anything but a copper twisted-pair type (HTTP 400).
        self.assertNotIn("duplex", iface)

    def test_the_duplex_is_never_sent_because_a_speed_does_not_say_the_media(self) -> None:
        for speed in ("100M", "1G", "10G", None):
            with self.subTest(speed=speed):
                overrides = {"oper_speed": speed} if speed else {}
                self.assertNotIn("duplex", self._one(_iface("eth1/5", duplex="full", **overrides)))

    def test_a_disabled_port_and_a_description(self) -> None:
        iface = self._one(_iface("eth1/2", admin_status="down", description="to server 12"))
        self.assertFalse(iface["enabled"])
        self.assertEqual(iface["description"], "to server 12")

    def test_speed_is_in_kbps_and_decides_the_type(self) -> None:
        cases = {
            "10G": (10_000_000, "10gbase-x-sfpp"),
            "25G": (25_000_000, "25gbase-x-sfp28"),
            "40G": (40_000_000, "40gbase-x-qsfpp"),
            "100G": (100_000_000, "100gbase-x-qsfp28"),
        }
        for speed, (kbps, nb_type) in cases.items():
            with self.subTest(speed=speed):
                iface = self._one(_iface("eth1/3", oper_speed=speed))
                self.assertEqual((iface["speed"], iface["type"]), (kbps, nb_type))

    def test_100m_and_1g_stay_other_because_copper_and_fiber_look_the_same(self) -> None:
        for speed, kbps in (("100M", 100_000), ("1G", 1_000_000)):
            with self.subTest(speed=speed):
                iface = self._one(_iface("eth1/3", oper_speed=speed))
                self.assertEqual((iface["speed"], iface["type"]), (kbps, "other"))

    def test_the_operational_speed_wins_over_the_configured_one(self) -> None:
        iface = self._one(_iface("eth1/3", speed="1G", oper_speed="10G"))
        self.assertEqual(iface["speed"], 10_000_000)
        self.assertEqual(self._one(_iface("eth1/4", speed="1G"))["speed"], 1_000_000)

    def test_an_unknown_speed_text_is_left_out_and_the_type_is_other(self) -> None:
        iface = self._one(_iface("eth1/3", oper_speed="auto"))
        self.assertNotIn("speed", iface)
        self.assertEqual(iface["type"], "other")

    def test_the_mac_is_normalised_and_an_unset_mac_is_left_out(self) -> None:
        self.assertEqual(
            self._one(_iface("vlan1", "svi", mac_address="00:22:bd:f8:19:ff"))["mac_address"],
            "00:22:BD:F8:19:FF",
        )
        self.assertNotIn("mac_address", self._one(_iface("eth1/1")))

    def test_addresses_use_the_global_namespace(self) -> None:
        iface = self._one(
            _iface(
                "lo1",
                "loopback",
                ipv4_addresses=[
                    {"address": "10.1.1.1/32", "type": "primary", "vrf": "Heroes:Heroes_Only"},
                    {"address": "192.168.1.1/32", "type": "secondary", "vrf": "Heroes:Heroes_Only"},
                ],
            )
        )
        self.assertEqual(
            iface["ip_addresses"],
            [
                {"address": "10.1.1.1/32", "namespace": "Global"},
                {"address": "192.168.1.1/32", "namespace": "Global"},
            ],
        )

    def test_svi_addresses_are_not_mapped_because_every_leaf_shares_the_anycast_gateway(
        self,
    ) -> None:
        iface = self._one(
            _iface(
                "vlan17",
                "svi",
                ipv4_addresses=[
                    {"address": "10.1.120.1/22", "type": "primary", "vrf": "Heroes:Heroes_Only"}
                ],
            )
        )
        self.assertNotIn("ip_addresses", iface)
        self.assertEqual(iface["type"], "virtual")

    def test_no_address_means_no_ip_key_so_existing_assignments_are_left_alone(self) -> None:
        self.assertNotIn("ip_addresses", self._one(_iface("eth1/1")))

    def test_the_kind_decides_the_type(self) -> None:
        self.assertEqual(self._one(_iface("po1", "port_channel"))["type"], "lag")
        self.assertEqual(self._one(_iface("lo0", "loopback"))["type"], "virtual")
        self.assertEqual(self._one(_iface("vlan13", "svi"))["type"], "virtual")
        self.assertEqual(self._one(_iface("mgmt0", "management", speed="1G"))["type"], "1000base-t")
        self.assertEqual(self._one(_iface("mgmt0", "management"))["type"], "other")

    def test_a_port_channel_member_points_at_its_channel(self) -> None:
        built = build_interfaces_from_aci_details(
            _entry(
                interfaces=[
                    _iface("eth1/15", port_channel="po1"),
                    _iface("po1", "port_channel", members=["eth1/15"]),
                ]
            )
        )
        by_name = {i["name"]: i for i in built}
        self.assertEqual(by_name["eth1/15"]["lag"], "po1")
        self.assertNotIn("lag", by_name["po1"])

    def test_aci_vlans_are_not_mapped_because_they_are_leaf_local_encapsulations(self) -> None:
        iface = self._one(
            _iface(
                "eth1/1",
                mode="trunk",
                access_vlan="5",
                native_vlan="7",
                allowed_vlans="39,97",
                vlan_id=13,
            )
        )
        for key in ("mode", "untagged_vlan", "tagged_vlans"):
            self.assertNotIn(key, iface)

    def test_rows_without_a_name_are_skipped(self) -> None:
        built = build_interfaces_from_aci_details(
            _entry(
                interfaces=[
                    {"kind": "physical"},
                    {"name": "  ", "kind": "physical"},
                    _iface("eth1/1"),
                ]
            )
        )
        self.assertEqual([i["name"] for i in built], ["eth1/1"])

    def test_a_missing_or_failed_fact_gives_no_interfaces(self) -> None:
        self.assertEqual(build_interfaces_from_aci_details({}), [])
        self.assertEqual(
            build_interfaces_from_aci_details({"interfaces": {"parsed": None, "error": "boom"}}), []
        )
        self.assertEqual(
            build_interfaces_from_aci_details(
                {"interfaces": {"parsed": {"not": "a list"}, "error": None}}
            ),
            [],
        )

    def test_the_input_is_not_mutated(self) -> None:
        entry = _entry(interfaces=[_iface("eth1/1", mtu=9000)])
        before = repr(entry)
        build_interfaces_from_aci_details(entry)
        self.assertEqual(repr(entry), before)


class BuildDeviceFieldsTests(unittest.TestCase):
    def test_serial_software_platform_and_device_type(self) -> None:
        fields = build_device_fields_from_aci_details(_entry(device=_DEVICE, software=_SOFTWARE))
        self.assertEqual(
            fields,
            {
                "serial": "TEP-1-101",
                "software_version": "simsw-6.1(4h)",
                "platform": {"name": "Cisco ACI"},
                "device_type": {"model": "N9K-C9396PX", "manufacturer": {"name": "Cisco"}},
            },
        )

    def test_role_status_and_location_are_never_derived(self) -> None:
        fields = build_device_fields_from_aci_details(_entry(device=_DEVICE, software=_SOFTWARE))
        for key in ("role", "status", "location", "name"):
            self.assertNotIn(key, fields)

    def test_missing_pieces_are_left_out(self) -> None:
        self.assertEqual(build_device_fields_from_aci_details({}), {})
        only_device = build_device_fields_from_aci_details(
            _entry(device={"node_id": 1, "model": None, "serial_number": "S"})
        )
        self.assertEqual(only_device, {"serial": "S", "platform": {"name": "Cisco ACI"}})

    def test_a_failed_device_fact_gives_nothing(self) -> None:
        self.assertEqual(
            build_device_fields_from_aci_details({"device": {"parsed": None, "error": "x"}}), {}
        )


def _device(entry: dict[str, Any], *, primary_ip4: str | None = None) -> DeviceContext:
    return DeviceContext(
        id="dev-1",
        name="leaf-1",
        hostname="leaf-1",
        source="aci",
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
        parsed={_KEY: entry},
        attribute_bags={
            "aci": {"node_id": 101, "pod_id": 1},
            "nautobot": {"role": {"name": "Leaf"}},
        },
        primary_ip4=primary_ip4,
    )


def _config(**overrides: Any) -> dict[str, Any]:
    return {
        "source_format": "aci_details",
        "config_source": "running",
        "parsed_key": _KEY,
        "attributes": ["interfaces", "device"],
        **overrides,
    }


async def _run(config: dict[str, Any], device: DeviceContext):
    return await execute(
        config=config,
        context=WorkflowContext(run_id="r", workflow_id="w", devices={"dev-1": device}),
        run=MagicMock(id=1),
        artifact_service=MagicMock(),
        node_id="n1",
        device_sessions=MagicMock(),
    )


class AciDetailsExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_writes_interfaces_and_device_fields_preserving_bags(self) -> None:
        device = _device(
            _entry(
                interfaces=[
                    _iface("eth1/1", oper_speed="10G", mtu=9000),
                    _iface(
                        "lo0",
                        "loopback",
                        ipv4_addresses=[
                            {"address": "10.0.64.64/32", "type": "primary", "vrf": "overlay-1"}
                        ],
                    ),
                ],
                device=_DEVICE,
                software=_SOFTWARE,
            )
        )
        outcomes = await _run(_config(), device)
        self.assertEqual([o.name for o in outcomes], ["success"])
        out = outcomes[0].context.devices["dev-1"]
        bag = out.attribute_bags["nautobot"]
        self.assertEqual(bag["role"], {"name": "Leaf"})  # untouched
        self.assertEqual(bag["serial"], "TEP-1-101")
        self.assertEqual(bag["platform"], {"name": "Cisco ACI"})
        self.assertEqual(bag["device_type"]["model"], "N9K-C9396PX")
        self.assertEqual([i["name"] for i in bag["interfaces"]], ["eth1/1", "lo0"])
        self.assertEqual(bag["interfaces"][0]["speed"], 10_000_000)
        self.assertIn(Capability.ATTRIBUTES, out.capabilities)
        self.assertEqual(out.attribute_bags["aci"], {"node_id": 101, "pod_id": 1})

    async def test_the_manufacturer_is_cisco_not_the_apic_vendor_string(self) -> None:
        device = _device(
            _entry(device={**_DEVICE, "vendor": "Cisco Systems, Inc"}, software=_SOFTWARE)
        )
        outcomes = await _run(_config(attributes=["device"]), device)
        bag = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]
        self.assertEqual(bag["device_type"]["manufacturer"], {"name": "Cisco"})

    async def test_device_only_group_skips_interfaces(self) -> None:
        device = _device(_entry(interfaces=[_iface("eth1/1")], device=_DEVICE, software=_SOFTWARE))
        outcomes = await _run(_config(attributes=["device"]), device)
        bag = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]
        self.assertNotIn("interfaces", bag)
        self.assertEqual(bag["serial"], "TEP-1-101")

    async def test_the_tep_loopback_never_becomes_the_primary_ip_by_default(self) -> None:
        # lo0 holds the fabric-internal TEP address: not a management address. The default
        # priorities (management interface, loopbackN) must not pick it.
        device = _device(
            _entry(
                interfaces=[
                    _iface(
                        "lo0",
                        "loopback",
                        ipv4_addresses=[
                            {"address": "10.0.64.64/32", "type": "primary", "vrf": "overlay-1"}
                        ],
                    )
                ]
            )
        )
        outcomes = await _run(_config(attributes=["interfaces"], update_primary_ipv4=True), device)
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        self.assertEqual(outcomes[0].context.devices, {})
        self.assertEqual(outcomes[1].context.devices["dev-1"].status, DeviceStatus.FAILED)

    async def test_a_custom_interface_pattern_is_the_explicit_way_to_pick_it(self) -> None:
        device = _device(
            _entry(
                interfaces=[
                    _iface(
                        "lo0",
                        "loopback",
                        ipv4_addresses=[
                            {"address": "10.0.64.64/32", "type": "primary", "vrf": "overlay-1"}
                        ],
                    )
                ]
            )
        )
        config = _config(
            attributes=["interfaces"],
            update_primary_ipv4=True,
            primary_ipv4_priority=[
                "custom_interface",
                "management_interface",
                "loopback_highest",
                "loopback_lowest",
            ],
            primary_ipv4_custom_pattern="^lo0$",
        )
        outcomes = await _run(config, device)
        iface = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"][0]
        self.assertTrue(iface["ip_addresses"][0]["is_primary"])

    async def test_the_management_interface_is_picked_when_it_has_an_address(self) -> None:
        device = _device(
            _entry(
                interfaces=[
                    _iface(
                        "mgmt0",
                        "management",
                        ipv4_addresses=[
                            {"address": "10.1.1.5/24", "type": "primary", "vrf": "mgmt:oob"}
                        ],
                    )
                ]
            )
        )
        outcomes = await _run(_config(attributes=["interfaces"], update_primary_ipv4=True), device)
        iface = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]["interfaces"][0]
        self.assertTrue(iface["ip_addresses"][0]["is_primary"])

    async def test_the_tep_loopback_address_is_not_exported_unless_it_is_the_primary(self) -> None:
        tep = {"address": "10.0.64.64/32", "type": "primary", "vrf": "overlay-1"}
        device = _device(
            _entry(
                interfaces=[
                    _iface("lo0", "loopback", ipv4_addresses=[tep]),
                    _iface(
                        "lo1",
                        "loopback",
                        ipv4_addresses=[{"address": "10.9.9.9/32", "type": "primary", "vrf": "x"}],
                    ),
                ]
            )
        )
        out = (await _run(_config(attributes=["interfaces"]), device))[0].context.devices["dev-1"]
        by_name = {i["name"]: i for i in out.attribute_bags["nautobot"]["interfaces"]}
        self.assertNotIn("ip_addresses", by_name["lo0"])
        self.assertEqual(by_name["lo1"]["ip_addresses"][0]["address"], "10.9.9.9/32")

        config = _config(
            attributes=["interfaces"],
            update_primary_ipv4=True,
            primary_ipv4_priority=[
                "custom_interface",
                "management_interface",
                "loopback_highest",
                "loopback_lowest",
            ],
            primary_ipv4_custom_pattern="^lo0$",
        )
        out = (await _run(config, device))[0].context.devices["dev-1"]
        lo0 = out.attribute_bags["nautobot"]["interfaces"][0]
        self.assertEqual(
            lo0["ip_addresses"],
            [{**{"address": "10.0.64.64/32", "namespace": "Global"}, "is_primary": True}],
        )

    async def test_fields_this_mapper_leaves_out_survive_the_merge(self) -> None:
        device = _device(
            _entry(interfaces=[_iface("eth1/1", oper_speed="10G"), _iface("vlan9", "svi")])
        )
        existing = [
            {
                "name": "eth1/1",
                "mode": "tagged",
                "untagged_vlan": 10,
                "tagged_vlans": [20, 30],
                "description": "old",
            },
            {"name": "vlan9", "ip_addresses": [{"address": "10.1.1.1/24", "namespace": "Global"}]},
            {"name": "eth9/9", "mode": "access"},
        ]
        device = device.model_copy(
            update={
                "attribute_bags": {
                    **device.attribute_bags,
                    "nautobot": {"role": {"name": "Leaf"}, "interfaces": existing},
                }
            }
        )
        out = (await _run(_config(attributes=["interfaces"]), device))[0].context.devices["dev-1"]
        by_name = {i["name"]: i for i in out.attribute_bags["nautobot"]["interfaces"]}
        self.assertEqual(by_name["eth1/1"]["mode"], "tagged")
        self.assertEqual(by_name["eth1/1"]["tagged_vlans"], [20, 30])
        self.assertEqual(by_name["eth1/1"]["speed"], 10_000_000)  # the new value still wins
        self.assertEqual(by_name["vlan9"]["ip_addresses"][0]["address"], "10.1.1.1/24")
        self.assertEqual(by_name["eth9/9"], {"name": "eth9/9", "mode": "access"})

    async def test_the_no_data_errors_name_the_fact_path(self) -> None:
        device = _device({"interfaces": {"parsed": None, "error": "boom"}})
        with self.assertRaises(ValueError) as caught:
            await _run(_config(), device)
        message = str(caught.exception)
        self.assertIn("parsed.aci_details.<fact>", message)
        self.assertNotIn(".running", message)

        mixed = _device(_entry(interfaces=[_iface("eth1/1")]))
        other = _device({"interfaces": {"parsed": None, "error": "boom"}}).model_copy(
            update={"id": "dev-2"}
        )
        outcomes = await execute(
            config=_config(attributes=["interfaces"]),
            context=WorkflowContext(
                run_id="r", workflow_id="w", devices={"dev-1": mixed, "dev-2": other}
            ),
            run=MagicMock(id=1),
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )
        error = outcomes[1].context.devices["dev-2"].errors[-1]
        self.assertIn("parsed.aci_details.<fact>", error.message)
        self.assertNotIn(".running", error.message)

    async def test_no_usable_facts_raises_naming_the_upstream_step(self) -> None:
        device = _device({"interfaces": {"parsed": None, "error": "boom"}})
        with self.assertRaisesRegex(ValueError, "Get Details from ACI"):
            await _run(_config(), device)

    async def test_startup_config_source_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "running"):
            await _run(
                _config(config_source="startup"), _device(_entry(interfaces=[_iface("eth1/1")]))
            )

    async def test_the_device_group_is_still_rejected_for_other_formats(self) -> None:
        with self.assertRaisesRegex(ValueError, "device"):
            await _run(
                _config(source_format="batfish", attributes=["device"]),
                _device(_entry(device=_DEVICE)),
            )

    async def test_a_catalyst_device_still_uses_its_own_vendor(self) -> None:
        """Dispatching the device fields by format must not change the Catalyst behaviour."""
        catalyst_entry = {
            "device": {
                "parsed": {"platform_id": "C9300-24P", "serial_number": "S1"},
                "error": None,
            },
            "software": {
                "parsed": {"software_type": "IOS-XE", "software_version": "17.12"},
                "error": None,
            },
        }
        device = DeviceContext(
            id="dev-1",
            name="sw1",
            hostname="sw1",
            source="catalyst_center",
            status=DeviceStatus.OK,
            parsed={"catalyst_details": catalyst_entry},
            attribute_bags={"catalyst_center": {"vendor": "Acme"}},
        )
        outcomes = await _run(
            _config(
                source_format="catalyst_details",
                parsed_key="catalyst_details",
                attributes=["device"],
            ),
            device,
        )
        bag = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]
        self.assertEqual(bag["device_type"]["manufacturer"], {"name": "Acme"})
        self.assertEqual(bag["platform"], {"name": "IOS-XE"})


if __name__ == "__main__":
    unittest.main()

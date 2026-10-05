"""Tests for the config-to-attributes ``catalyst_details`` source format."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from workflow_steps.config_to_attributes.catalyst_details import (
    build_device_fields_from_catalyst_details,
    build_interfaces_from_catalyst_details,
)
from workflow_steps.config_to_attributes.executor import execute

_KEY = "catalyst_details"


def _iface(name: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": name,
        "description": None,
        "status": "up",
        "admin_status": "UP",
        "interface_type": "Physical",
        "port_mode": "access",
        "port_type": "Ethernet Port",
        "speed": "1000000",
        "duplex": "FullDuplex",
        "mtu": 1500,
        "mac_address": "52:54:00:02:19:56",
        "ipv4_address": None,
        "ipv4_mask": None,
        "vlan_id": "1",
        "native_vlan_id": "1",
        "voice_vlan": None,
    }
    return {**base, **overrides}


_DEVICE_FACT = {
    "id": "6b3dc2dd",
    "hostname": "sw1",
    "management_ip": "10.10.20.175",
    "platform_id": "C9KV-UADP-8P",
    "serial_number": "CML12345UAD",
    "device_type": "Cisco Catalyst 9000 UADP 8 Port Virtual Switch",
    "role": "ACCESS",
}
_SOFTWARE_FACT = {"software_type": "IOS-XE", "software_version": "17.12.1prd9"}


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
    def test_routed_interface_with_ip(self) -> None:
        built = build_interfaces_from_catalyst_details(
            _entry(
                interfaces=[
                    _iface(
                        "GigabitEthernet0/0",
                        port_mode="routed",
                        ipv4_address="10.10.20.175",
                        ipv4_mask="255.255.255.0",
                        vlan_id="0",
                        native_vlan_id=None,
                    )
                ]
            )
        )
        self.assertEqual(len(built), 1)
        iface = built[0]
        self.assertEqual(iface["name"], "GigabitEthernet0/0")
        self.assertEqual(iface["status"], "Active")
        self.assertEqual(iface["type"], "1000base-t")
        self.assertTrue(iface["enabled"])
        self.assertEqual(iface["mtu"], 1500)
        self.assertEqual(iface["mac_address"], "52:54:00:02:19:56")
        self.assertEqual(
            iface["ip_addresses"], [{"address": "10.10.20.175/24", "namespace": "Global"}]
        )
        self.assertNotIn("mode", iface)
        self.assertNotIn("untagged_vlan", iface)

    def test_access_port_gets_untagged_vlan(self) -> None:
        built = build_interfaces_from_catalyst_details(
            _entry(interfaces=[_iface("GigabitEthernet1/0/7", vlan_id="101")])
        )
        self.assertEqual(built[0]["mode"], "access")
        self.assertEqual(built[0]["untagged_vlan"], 101)

    def test_trunk_port_uses_native_vlan(self) -> None:
        built = build_interfaces_from_catalyst_details(
            _entry(
                interfaces=[_iface("GigabitEthernet1/0/1", port_mode="trunk", native_vlan_id="5")]
            )
        )
        self.assertEqual(built[0]["mode"], "trunk")
        self.assertEqual(built[0]["untagged_vlan"], 5)
        self.assertNotIn("tagged_vlans", built[0])

    def test_vlan_zero_or_invalid_is_ignored(self) -> None:
        built = build_interfaces_from_catalyst_details(
            _entry(
                interfaces=[
                    _iface("Gi1", vlan_id="0"),
                    _iface("Gi2", vlan_id="abc"),
                    _iface("Gi3", port_mode="trunk", native_vlan_id=None),
                ]
            )
        )
        for iface in built:
            self.assertNotIn("untagged_vlan", iface)

    def test_admin_down_is_disabled_and_description_kept(self) -> None:
        built = build_interfaces_from_catalyst_details(
            _entry(
                interfaces=[
                    _iface(
                        "Vlan1",
                        admin_status="DOWN",
                        port_mode="routed",
                        description="Prod",
                        mac_address=None,
                        mtu=None,
                    )
                ]
            )
        )
        iface = built[0]
        self.assertFalse(iface["enabled"])
        self.assertEqual(iface["description"], "Prod")
        self.assertEqual(iface["type"], "virtual")
        self.assertNotIn("mac_address", iface)
        self.assertNotIn("mtu", iface)

    def test_skips_nameless_and_non_dict_entries(self) -> None:
        built = build_interfaces_from_catalyst_details(
            _entry(interfaces=[_iface(""), "junk", _iface("Loopback0")])  # type: ignore[list-item]
        )
        self.assertEqual([i["name"] for i in built], ["Loopback0"])

    def test_missing_or_failed_fact_yields_nothing(self) -> None:
        self.assertEqual(build_interfaces_from_catalyst_details({}), [])
        self.assertEqual(
            build_interfaces_from_catalyst_details(
                {"interfaces": {"parsed": None, "error": "boom"}}
            ),
            [],
        )


class BuildDeviceFieldsTests(unittest.TestCase):
    def test_full_mapping(self) -> None:
        fields = build_device_fields_from_catalyst_details(
            _entry(device=_DEVICE_FACT, software=_SOFTWARE_FACT), "Cisco"
        )
        self.assertEqual(
            fields,
            {
                "serial": "CML12345UAD",
                "software_version": "17.12.1prd9",
                "platform": {"name": "IOS-XE"},
                "device_type": {"model": "C9KV-UADP-8P", "manufacturer": {"name": "Cisco"}},
            },
        )

    def test_model_falls_back_to_device_type_and_manufacturer_defaults(self) -> None:
        fields = build_device_fields_from_catalyst_details(
            _entry(device={**_DEVICE_FACT, "platform_id": None}), None
        )
        self.assertEqual(
            fields["device_type"],
            {
                "model": "Cisco Catalyst 9000 UADP 8 Port Virtual Switch",
                "manufacturer": {"name": "Cisco"},
            },
        )

    def test_omits_empty_values_and_never_emits_role_status_location(self) -> None:
        fields = build_device_fields_from_catalyst_details(
            _entry(device={"serial_number": " ", "role": "ACCESS", "location_name": "x"}), "Cisco"
        )
        self.assertEqual(fields, {})

    def test_failed_facts_yield_empty(self) -> None:
        self.assertEqual(build_device_fields_from_catalyst_details({}, "Cisco"), {})


def _device(entry: dict[str, Any], *, primary_ip4: str | None = None) -> DeviceContext:
    return DeviceContext(
        id="dev-1",
        name="sw1",
        hostname="10.10.20.175",
        source="catalyst_center",
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
        parsed={_KEY: entry},
        attribute_bags={
            "catalyst_center": {"vendor": "Cisco"},
            "nautobot": {"role": {"name": "Access"}},
        },
        primary_ip4=primary_ip4,
    )


def _config(**overrides: Any) -> dict[str, Any]:
    return {
        "source_format": "catalyst_details",
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


class CatalystDetailsExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_writes_interfaces_and_device_fields_preserving_bag(self) -> None:
        device = _device(
            _entry(
                interfaces=[
                    _iface(
                        "GigabitEthernet0/0",
                        port_mode="routed",
                        ipv4_address="10.10.20.175",
                        ipv4_mask="255.255.255.0",
                    )
                ],
                device=_DEVICE_FACT,
                software=_SOFTWARE_FACT,
            ),
            primary_ip4="10.10.20.175",
        )
        outcomes = await _run(_config(), device)
        self.assertEqual([o.name for o in outcomes], ["success"])
        out = outcomes[0].context.devices["dev-1"]
        bag = out.attribute_bags["nautobot"]
        self.assertEqual(bag["role"], {"name": "Access"})
        self.assertEqual(bag["serial"], "CML12345UAD")
        self.assertEqual(bag["platform"], {"name": "IOS-XE"})
        self.assertEqual(bag["device_type"]["model"], "C9KV-UADP-8P")
        self.assertEqual(bag["interfaces"][0]["name"], "GigabitEthernet0/0")
        self.assertIn(Capability.ATTRIBUTES, out.capabilities)
        # the raw bag is untouched
        self.assertEqual(out.attribute_bags["catalyst_center"], {"vendor": "Cisco"})

    async def test_vendor_comes_from_catalyst_bag(self) -> None:
        device = _device(_entry(device=_DEVICE_FACT, software=_SOFTWARE_FACT))
        device = device.model_copy(
            update={"attribute_bags": {"catalyst_center": {"vendor": "Acme"}}}
        )
        outcomes = await _run(_config(attributes=["device"]), device)
        bag = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]
        self.assertEqual(bag["device_type"]["manufacturer"], {"name": "Acme"})

    async def test_device_only_group_skips_interfaces(self) -> None:
        device = _device(
            _entry(interfaces=[_iface("Gi1")], device=_DEVICE_FACT, software=_SOFTWARE_FACT)
        )
        outcomes = await _run(_config(attributes=["device"]), device)
        bag = outcomes[0].context.devices["dev-1"].attribute_bags["nautobot"]
        self.assertNotIn("interfaces", bag)
        self.assertEqual(bag["serial"], "CML12345UAD")

    async def test_primary_ipv4_verified_against_interfaces(self) -> None:
        device = _device(
            _entry(interfaces=[_iface("Gi1", port_mode="routed")]), primary_ip4="10.10.20.175"
        )
        outcomes = await _run(_config(attributes=["interfaces"]), device)
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        failed = outcomes[1].context.devices["dev-1"]
        self.assertEqual(failed.errors[0].code, "primary_ipv4_not_found")

    async def test_update_primary_ipv4_picks_management_interface(self) -> None:
        device = _device(
            _entry(
                interfaces=[
                    _iface(
                        "Loopback0",
                        port_mode="routed",
                        ipv4_address="10.1.1.1",
                        ipv4_mask="255.255.255.255",
                    )
                ]
            )
        )
        outcomes = await _run(_config(attributes=["interfaces"], update_primary_ipv4=True), device)
        addr = (
            outcomes[0]
            .context.devices["dev-1"]
            .attribute_bags["nautobot"]["interfaces"][0]["ip_addresses"][0]
        )
        self.assertTrue(addr["is_primary"])

    async def test_no_usable_facts_raises(self) -> None:
        device = _device({"interfaces": {"parsed": None, "error": "boom"}})
        with self.assertRaisesRegex(ValueError, "Get Details from Catalyst Center"):
            await _run(_config(), device)

    async def test_startup_config_source_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "running"):
            await _run(
                _config(config_source="startup"), _device(_entry(interfaces=[_iface("Gi1")]))
            )

    async def test_device_group_rejected_for_other_formats(self) -> None:
        with self.assertRaisesRegex(ValueError, "device"):
            await _run(
                _config(source_format="batfish", attributes=["device"]),
                _device(_entry(interfaces=[_iface("Gi1")])),
            )


if __name__ == "__main__":
    unittest.main()

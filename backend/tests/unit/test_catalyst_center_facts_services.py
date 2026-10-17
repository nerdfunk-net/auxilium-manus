"""Details, health and topology services: payload shapes captured from the DevNet sandbox."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterValidationError,
)
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.catalyst_center.details_service import CatalystCenterDetailsService
from services.catalyst_center.health_service import CatalystCenterHealthService
from services.catalyst_center.topology_service import CatalystCenterTopologyService

CREDS = CatalystCenterCredentials("https://dnac", "u", "p")
INTENT = "/dna/intent/api/v1"


def _client(*responses):
    client = AsyncMock()
    client.request.side_effect = list(responses)
    return client


class DetailsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_device_and_software_from_one_request(self) -> None:
        client = _client(
            {
                "response": {
                    "hostname": "sw1",
                    "managementIpAddress": "10.10.20.175",
                    "platformId": "C9KV-UADP-8P",
                    "serialNumber": "CML12345UAD",
                    "softwareType": "IOS-XE",
                    "softwareVersion": "17.12.1prd9",
                    "role": "ACCESS",
                    "reachabilityStatus": "Reachable",
                    "locationName": None,
                    "upTime": "5 days, 1:17:48.00",
                    "series": "Cisco Catalyst 9000 Series Virtual Switches",
                }
            }
        )
        device, software = await CatalystCenterDetailsService(
            client, CREDS
        ).get_device_and_software("abc-1")
        client.request.assert_awaited_once_with(CREDS, "GET", f"{INTENT}/network-device/abc-1")
        self.assertEqual(
            (device.hostname, device.role, device.location_name), ("sw1", "ACCESS", None)
        )
        self.assertEqual(device.reachability_status, "Reachable")
        self.assertEqual(
            (software.software_type, software.software_version), ("IOS-XE", "17.12.1prd9")
        )

    async def test_interfaces_are_whitelisted_and_coerced(self) -> None:
        client = _client(
            {
                "response": [
                    {
                        "portName": "GigabitEthernet1/0/1",
                        "status": "up",
                        "adminStatus": "UP",
                        "speed": "1000000",
                        "duplex": "FullDuplex",
                        "mtu": "1500",
                        "ipv4Address": "10.1.1.1",
                        "nativeVlanId": "",
                        "serialNo": "must-not-leak",
                    },
                    "not-a-dict",
                ]
            }
        )
        interfaces = await CatalystCenterDetailsService(client, CREDS).get_interfaces("abc-1")
        self.assertEqual(len(interfaces), 1)
        iface = interfaces[0]
        self.assertEqual(
            (iface.name, iface.mtu, iface.native_vlan_id), ("GigabitEthernet1/0/1", 1500, None)
        )
        self.assertNotIn("serial", " ".join(iface.model_dump()))

    async def test_vlans(self) -> None:
        client = _client(
            {
                "response": [
                    {
                        "vlanNumber": 101,
                        "vlanType": "Prod",
                        "numberOfIPs": 256,
                        "prefix": "24",
                        "interfaceName": "Vlan101",
                        "ipAddress": "172.16.101.254",
                    }
                ]
            }
        )
        (vlan,) = await CatalystCenterDetailsService(client, CREDS).get_vlans("abc-1")
        self.assertEqual((vlan.vlan_number, vlan.number_of_ips, vlan.prefix), (101, 256, "24"))
        self.assertEqual(client.request.await_args.args[2], f"{INTENT}/network-device/abc-1/vlan")

    async def test_compliance_combines_overall_and_detail(self) -> None:
        client = _client(
            {"response": {"complianceStatus": "COMPLIANT", "lastUpdateTime": 1790608509617}},
            {
                "response": [
                    {
                        "complianceType": "RUNNING_CONFIG",
                        "status": "COMPLIANT",
                        "state": "SUCCESS",
                        "lastSyncTime": 1790608483272,
                        "remediationSupported": False,
                        "ackStatus": "UNACKNOWLEDGED",
                    }
                ]
            },
        )
        result = await CatalystCenterDetailsService(client, CREDS).get_compliance("abc-1")
        paths = [c.args[2] for c in client.request.await_args_list]
        self.assertEqual(paths, [f"{INTENT}/compliance/abc-1", f"{INTENT}/compliance/abc-1/detail"])
        self.assertEqual(result.status, "COMPLIANT")
        self.assertEqual(result.items[0].compliance_type, "RUNNING_CONFIG")
        self.assertIs(result.items[0].remediation_supported, False)

    async def test_unexpected_body_and_unsafe_id(self) -> None:
        service = CatalystCenterDetailsService(_client({"response": "oops"}), CREDS)
        with self.assertRaises(CatalystCenterAPIError):
            await service.get_interfaces("abc-1")
        with self.assertRaises(CatalystCenterValidationError):
            await service.get_vlans("../x")


class HealthServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_device_detail_is_normalized(self) -> None:
        client = _client(
            {
                "response": {
                    "overallHealth": 10.0,
                    "cpu": "26.25",
                    "memory": "67.89",
                    "memoryScore": 10.0,
                    "communicationState": "REACHABLE",
                    "haStatus": "Non-redundant",
                    "ringStatus": False,
                    "lastBootTime": 1790000000000,
                    "nwDeviceRole": "ACCESS",
                }
            }
        )
        health = await CatalystCenterHealthService(client, CREDS).get_device_health("abc-1")
        call = client.request.await_args
        self.assertEqual(call.args[2], f"{INTENT}/device-detail")
        self.assertEqual(call.kwargs["params"], {"identifier": "uuid", "searchBy": "abc-1"})
        self.assertEqual((health.overall_health, health.cpu, health.memory), (10.0, 26.25, 67.89))
        self.assertIs(health.ring_status, False)
        self.assertEqual(health.role, "ACCESS")

    async def test_empty_response_is_an_error(self) -> None:
        with self.assertRaises(CatalystCenterAPIError):
            await CatalystCenterHealthService(_client({"response": {}}), CREDS).get_device_health(
                "a"
            )


_GRAPH = {
    "response": {
        "nodes": [
            {"id": "n1", "label": "sw1", "ip": "10.0.0.1", "role": "ACCESS", "nodeType": "device"},
            {"id": "n2", "label": "sw2", "ip": "10.0.0.2"},
            {"id": "n3", "label": "sw3"},
        ],
        "links": [
            {
                "id": "l1",
                "source": "n1",
                "target": "n2",
                "startPortName": "Gi1/0/1",
                "endPortName": "Gi1/0/2",
                "startPortSpeed": "1000000",
                "endPortSpeed": "1000000",
                "linkStatus": "up",
            },
            {"source": "n3", "target": "n1", "startPortName": "Gi1/0/9", "endPortName": "Gi1/0/3"},
            {"source": "n2", "target": "n3"},
        ],
    }
}


class TopologyServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_physical_topology_and_per_device_slice(self) -> None:
        client = _client(_GRAPH)
        topology = await CatalystCenterTopologyService(client, CREDS).get_physical_topology()
        self.assertEqual(client.request.await_args.args[2], f"{INTENT}/topology/physical-topology")
        sliced = topology.for_device("n1")
        self.assertEqual(sliced["node"]["label"], "sw1")
        local_view = {link["remote_name"]: link for link in sliced["links"]}
        self.assertEqual(set(local_view), {"sw2", "sw3"})
        self.assertEqual(local_view["sw2"]["local_port"], "Gi1/0/1")
        self.assertEqual(local_view["sw2"]["remote_port"], "Gi1/0/2")
        # the link stored as n3 -> n1 is shown from n1's side
        self.assertEqual(local_view["sw3"]["local_port"], "Gi1/0/3")
        self.assertEqual(local_view["sw3"]["remote_port"], "Gi1/0/9")

    async def test_device_outside_the_graph_gets_empty_result(self) -> None:
        topology = await CatalystCenterTopologyService(
            _client(_GRAPH), CREDS
        ).get_physical_topology()
        self.assertEqual(topology.for_device("zzz"), {"node": None, "links": []})

    async def test_l3_protocol_path_and_validation(self) -> None:
        client = _client(_GRAPH)
        service = CatalystCenterTopologyService(client, CREDS)
        await service.get_l3_topology("ospf")
        self.assertEqual(client.request.await_args.args[2], f"{INTENT}/topology/l3/ospf")
        with self.assertRaises(CatalystCenterValidationError):
            await service.get_l3_topology("bgp")  # rejected by the controller (HTTP 400)

    async def test_malformed_entries_are_skipped_and_bad_body_raises(self) -> None:
        graph = {"response": {"nodes": [{"label": "no id"}, "x"], "links": [{"source": "a"}]}}
        topology = await CatalystCenterTopologyService(
            _client(graph), CREDS
        ).get_physical_topology()
        self.assertEqual((topology.nodes, topology.links), ((), ()))
        with self.assertRaises(CatalystCenterAPIError):
            await CatalystCenterTopologyService(
                _client({"response": []}), CREDS
            ).get_physical_topology()

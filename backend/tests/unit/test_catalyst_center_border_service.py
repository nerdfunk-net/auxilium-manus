"""CatalystCenterBorderService: border nodes, transits and the three handoff kinds."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from models.catalyst_center_facts import CatalystCenterFabricDevice
from services.catalyst_center.border_service import (
    IP_TRANSITS_PATH,
    LAYER2_HANDOFFS_PATH,
    SDA_TRANSITS_PATH,
    TRANSITS_PATH,
    CatalystCenterBorderService,
)
from services.catalyst_center.common.exceptions import (
    CatalystCenterNotFoundError,
    CatalystCenterValidationError,
)
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.catalyst_center.fabric_service import (
    FABRIC_DEVICES_PATH,
    FABRIC_SITES_PATH,
    VIRTUAL_NETWORKS_PATH,
)

SITE = "/dna/intent/api/v1/site"


def _service(routes: dict, errors: dict | None = None):
    calls: list = []
    client = AsyncMock()

    async def request(creds, method, path, *, params=None, json=None):
        calls.append((path, params))
        if errors and path in errors:
            raise errors[path]
        if path == SITE:
            return {"response": [{"id": "s1", "siteNameHierarchy": "Global/Berlin"}]}
        if path == FABRIC_SITES_PATH:
            return {"response": [{"id": "f1", "siteId": "s1"}]}
        if path == VIRTUAL_NETWORKS_PATH:
            return {"response": []}
        return {"response": routes.get(path, [])}

    client.request = request
    creds = CatalystCenterCredentials("https://dnac", "admin", "pw")
    return CatalystCenterBorderService(client, creds), calls


BORDER = CatalystCenterFabricDevice(
    device_id="d1", fabric_id="f1", fabric_site="Global/Berlin", roles=("BORDER_NODE",)
)


def test_only_border_nodes_are_listed() -> None:
    service, _ = _service(
        {
            FABRIC_DEVICES_PATH: [
                {"networkDeviceId": "d1", "deviceRoles": ["BORDER_NODE", "EDGE_NODE"]},
                {"networkDeviceId": "d2", "deviceRoles": ["EDGE_NODE"]},
            ]
        }
    )

    borders, incomplete = asyncio.run(service.list_borders())

    assert [b.device_id for b in borders] == ["d1"] and incomplete == ()


def test_transits_map_id_to_name_and_type_and_a_404_is_empty() -> None:
    service, _ = _service(
        {TRANSITS_PATH: [{"id": "t1", "name": "WAN", "type": "IP_BASED_TRANSIT"}, {"name": "x"}]}
    )
    transits = asyncio.run(service.list_transits())
    assert transits["t1"].name == "WAN" and transits["t1"].transit_type == "IP_BASED_TRANSIT"
    assert list(transits) == ["t1"]

    missing, _ = _service({}, {TRANSITS_PATH: CatalystCenterNotFoundError("x")})
    assert asyncio.run(missing.list_transits()) == {}
    # The transit tool asks strictly: a missing API is not "no transits".
    try:
        asyncio.run(missing.list_transits(missing_ok=False))
    except CatalystCenterNotFoundError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected not found")


def test_handoffs_are_normalized_per_kind_with_transit_names() -> None:
    service, calls = _service(
        {
            TRANSITS_PATH: [{"id": "t1", "name": "WAN"}],
            IP_TRANSITS_PATH: [
                {
                    "transitNetworkId": "t1",
                    "interfaceName": "TenGigabitEthernet1/0/1",
                    "virtualNetworkName": "CORP",
                    "vlanId": "3001",
                    "externalConnectivityIpPoolName": "handoff-pool",
                    "localIpAddress": "10.9.9.1/30",
                    "remoteIpAddress": "10.9.9.2/30",
                }
            ],
            SDA_TRANSITS_PATH: [
                {
                    "transitNetworkId": "t1",
                    "connectedToInternet": "true",
                    "isMulticastOverTransitEnabled": False,
                }
            ],
            LAYER2_HANDOFFS_PATH: [
                {"interfaceName": "Gi1/0/5", "internalVlanId": 1021, "externalVlanId": "121"}
            ],
        }
    )
    transits = asyncio.run(service.list_transits())

    h = asyncio.run(service.read_handoffs(BORDER, transits))

    ip = h.ip_transits[0]
    assert (ip.transit_name, ip.interface_name, ip.virtual_network, ip.vlan_id) == (
        "WAN",
        "TenGigabitEthernet1/0/1",
        "CORP",
        3001,
    )
    assert ip.ip_pool == "handoff-pool" and ip.remote_ip == "10.9.9.2/30"
    assert h.sda_transits[0].connected_to_internet is True
    assert h.sda_transits[0].multicast_over_transit is False
    assert (
        h.layer2[0].interface_name,
        h.layer2[0].internal_vlan_id,
        h.layer2[0].external_vlan_id,
    ) == (
        "Gi1/0/5",
        1021,
        121,
    )
    assert h.unavailable == ()
    handoff_calls = [
        p
        for path, p in calls
        if path in (IP_TRANSITS_PATH, SDA_TRANSITS_PATH, LAYER2_HANDOFFS_PATH)
    ]
    assert all(p["fabricId"] == "f1" and p["networkDeviceId"] == "d1" for p in handoff_calls)


def test_a_failing_kind_is_unavailable_and_the_others_survive() -> None:
    service, _ = _service(
        {LAYER2_HANDOFFS_PATH: [{"interfaceName": "Gi1/0/5"}]},
        {
            IP_TRANSITS_PATH: CatalystCenterNotFoundError("x"),
            SDA_TRANSITS_PATH: CatalystCenterValidationError("bad"),
        },
    )

    h = asyncio.run(service.read_handoffs(BORDER, {}))

    assert h.unavailable == ("ip_transits", "sda_transits")
    assert [x.interface_name for x in h.layer2] == ["Gi1/0/5"]


def test_an_unsafe_id_is_refused_before_any_request() -> None:
    service, calls = _service({})
    bad = CatalystCenterFabricDevice(device_id="../x", fabric_id="f1", roles=("BORDER_NODE",))

    h = asyncio.run(service.read_handoffs(bad, {}))

    # No request, and no exception that would discard the other borders of the page.
    assert calls == []
    assert set(h.unavailable) == {"ip_transits", "sda_transits", "layer2"}


def test_unrecognised_rows_are_skipped_and_the_kind_is_unavailable() -> None:
    service, _ = _service(
        {IP_TRANSITS_PATH: [{"unexpected": 1}], LAYER2_HANDOFFS_PATH: [{"interfaceName": "Te1"}]}
    )

    h = asyncio.run(service.read_handoffs(BORDER, {}))

    assert h.ip_transits == () and "ip_transits" in h.unavailable
    assert len(h.layer2) == 1 and "layer2" not in h.unavailable


def test_a_rate_limit_on_one_kind_does_not_fail_the_border() -> None:
    from services.catalyst_center.common.exceptions import CatalystCenterRateLimitError

    service, _ = _service({}, {IP_TRANSITS_PATH: CatalystCenterRateLimitError("x")})

    h = asyncio.run(service.read_handoffs(BORDER, {}))

    assert h.unavailable == ("ip_transits",)


def test_listing_borders_does_not_read_virtual_networks() -> None:
    service, calls = _service({})

    asyncio.run(service.list_borders())

    assert VIRTUAL_NETWORKS_PATH not in [path for path, _ in calls]


def test_transit_settings_are_read_and_unsafe_control_plane_ids_dropped() -> None:
    service, _ = _service(
        {
            TRANSITS_PATH: [
                {
                    "id": "t1",
                    "name": "WAN",
                    "type": "IP_BASED_TRANSIT",
                    "ipTransitSettings": {
                        "routingProtocolName": "BGP",
                        "autonomousSystemNumber": 65001,
                    },
                },
                {
                    "id": "t2",
                    "name": "SDA",
                    "type": "SDA_LISP_PUB_SUB_TRANSIT",
                    "sdaTransitSettings": {
                        "isMulticastOverTransitEnabled": "true",
                        "controlPlaneNetworkDeviceIds": ["cp-1", "../x", 5, ""],
                    },
                },
                {"id": "t3", "ipTransitSettings": "junk"},
            ]
        }
    )

    transits = asyncio.run(service.list_transits())

    assert (transits["t1"].routing_protocol, transits["t1"].autonomous_system_number) == (
        "BGP",
        "65001",
    )
    assert transits["t2"].multicast_over_transit is True
    assert transits["t2"].control_plane_device_ids == ("cp-1", "5")
    assert transits["t3"].routing_protocol is None

"""CatalystCenterFabricService: fabric sites, fabric devices, virtual networks, underlay-only."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from services.catalyst_center.common.exceptions import (
    CatalystCenterNotFoundError,
    CatalystCenterTooManySitesError,
    CatalystCenterValidationError,
)
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.catalyst_center.fabric_service import (
    FABRIC_DEVICES_PATH,
    FABRIC_SITES_PATH,
    PAGE_SIZE,
    VIRTUAL_NETWORKS_PATH,
    CatalystCenterFabricService,
)

SITE = "/dna/intent/api/v1/site"
MEMBERSHIP = "/dna/intent/api/v1/membership"


def _creds() -> CatalystCenterCredentials:
    return CatalystCenterCredentials("https://dnac", "admin", "pw")


def _client(*, fabric_sites=None, fabric_devices=None, vns=None, members=None, missing=False):
    client = AsyncMock()
    client.calls = []

    async def request(creds, method, path, *, params=None, json=None):
        client.calls.append((path, params))
        if missing and path.startswith("/dna/intent/api/v1/sda"):
            raise CatalystCenterNotFoundError("nope")
        if path == SITE:
            return {
                "response": [
                    {"id": "s1", "siteNameHierarchy": "Global/Berlin"},
                    {"id": "s2", "siteNameHierarchy": "Global/Munich"},
                ]
            }
        if path == FABRIC_SITES_PATH:
            return {"response": fabric_sites or []}
        if path == FABRIC_DEVICES_PATH:
            return {"response": (fabric_devices or {}).get(params["fabricId"], [])}
        if path == VIRTUAL_NETWORKS_PATH:
            return {"response": vns or []}
        if path.startswith(MEMBERSHIP + "/"):
            ids = (members or {}).get(path.rsplit("/", 1)[-1], [])
            return {"device": [{"response": [{"instanceUuid": i} for i in ids]}]}
        raise AssertionError(path)

    client.request = request
    return client


def _run(client, **kwargs):
    return asyncio.run(CatalystCenterFabricService(client, _creds()).read_fabric(**kwargs))


def test_no_fabric_is_an_empty_fabric() -> None:
    fabric = _run(_client())

    assert fabric.sites == () and fabric.devices == () and fabric.virtual_networks == ()


def test_roles_sites_and_virtual_networks_are_normalized() -> None:
    client = _client(
        fabric_sites=[{"id": "f1", "siteId": "s1"}, {"id": "f2", "siteId": "s2"}],
        fabric_devices={
            "f1": [
                {"networkDeviceId": "d1", "deviceRoles": ["EDGE_NODE", "BORDER_NODE", "EDGE_NODE"]},
                {"networkDeviceId": "", "deviceRoles": ["EDGE_NODE"]},  # skipped
                {"networkDeviceId": "d9"},  # no roles list: skipped
            ],
            "f2": [{"networkDeviceId": "d2", "deviceRoles": ["CONTROL_PLANE_NODE"]}],
        },
        vns=[
            {"virtualNetworkName": "CORP", "fabricIds": ["f2", "f1", "unknown"]},
            {"virtualNetworkName": ""},
        ],
    )

    fabric = _run(client)

    assert [(s.fabric_id, s.site_name) for s in fabric.sites] == [
        ("f1", "Global/Berlin"),
        ("f2", "Global/Munich"),
    ]
    assert [(d.device_id, d.fabric_site, d.roles) for d in fabric.devices] == [
        ("d1", "Global/Berlin", ("BORDER_NODE", "EDGE_NODE")),
        ("d2", "Global/Munich", ("CONTROL_PLANE_NODE",)),
    ]
    assert [(n.name, n.fabric_sites) for n in fabric.virtual_networks] == [
        ("CORP", ("Global/Berlin", "Global/Munich"))
    ]
    assert fabric.underlay_only == ()


def test_underlay_only_is_membership_minus_fabric_devices() -> None:
    client = _client(
        fabric_sites=[{"id": "f1", "siteId": "s1"}],
        fabric_devices={"f1": [{"networkDeviceId": "d1", "deviceRoles": ["EDGE_NODE"]}]},
        members={"s1": ["d1", "d7", "d8"]},
    )

    fabric = _run(client, include_underlay=True)

    assert [(u.device_id, u.fabric_site) for u in fabric.underlay_only] == [
        ("d7", "Global/Berlin"),
        ("d8", "Global/Berlin"),
    ]


def test_membership_is_not_read_without_include_underlay() -> None:
    client = _client(fabric_sites=[{"id": "f1", "siteId": "s1"}])

    _run(client)

    assert not any(path.startswith(MEMBERSHIP) for path, _ in client.calls)


def test_a_missing_sda_api_surfaces_as_not_found() -> None:
    with pytest.raises(CatalystCenterNotFoundError):
        _run(_client(missing=True))


def test_an_unexpected_body_is_a_validation_error() -> None:
    client = AsyncMock()

    async def request(creds, method, path, *, params=None, json=None):
        return {"response": []} if path == SITE else {"response": "boom"}

    client.request = request
    with pytest.raises(CatalystCenterValidationError):
        _run(client)


def test_paging_continues_until_a_short_page() -> None:
    client = AsyncMock()
    seen: list[int] = []

    async def request(creds, method, path, *, params=None, json=None):
        if path == VIRTUAL_NETWORKS_PATH:
            seen.append(params["offset"])
            n = PAGE_SIZE if params["offset"] == 1 else 1
            return {
                "response": [{"virtualNetworkName": f"vn{params['offset']}-{i}"} for i in range(n)]
            }
        return {"response": []}

    client.request = request
    fabric = _run(client)

    assert seen == [1, 1 + PAGE_SIZE]
    assert len(fabric.virtual_networks) == PAGE_SIZE + 1


def test_too_many_fabric_sites_are_refused() -> None:
    client = _client(fabric_sites=[{"id": f"f{i}", "siteId": "s1"} for i in range(101)])

    with pytest.raises(CatalystCenterValidationError):
        _run(client)


def test_a_missing_virtual_network_list_keeps_the_membership_answer() -> None:
    client = _client(
        fabric_sites=[{"id": "f1", "siteId": "s1"}],
        fabric_devices={"f1": [{"networkDeviceId": "d1", "deviceRoles": ["EDGE_NODE"]}]},
    )
    original = client.request

    async def request(creds, method, path, *, params=None, json=None):
        if path == VIRTUAL_NETWORKS_PATH:
            raise CatalystCenterNotFoundError("nope")
        return await original(creds, method, path, params=params, json=json)

    client.request = request
    fabric = _run(client)

    assert [d.device_id for d in fabric.devices] == ["d1"] and fabric.virtual_networks == ()


def test_a_fabric_site_whose_devices_404_is_incomplete_not_fatal() -> None:
    client = _client(
        fabric_sites=[{"id": "f1", "siteId": "s1"}, {"id": "f2", "siteId": "s2"}],
        fabric_devices={"f2": [{"networkDeviceId": "d2", "deviceRoles": ["EDGE_NODE"]}]},
    )
    original = client.request

    async def request(creds, method, path, *, params=None, json=None):
        if path == FABRIC_DEVICES_PATH and params["fabricId"] == "f1":
            raise CatalystCenterNotFoundError("nope")
        return await original(creds, method, path, params=params, json=json)

    client.request = request
    fabric = _run(client)

    assert [d.device_id for d in fabric.devices] == ["d2"]
    assert fabric.incomplete_sites == ("Global/Berlin",)


def test_fabric_site_filter_limits_the_per_site_reads() -> None:
    client = _client(
        fabric_sites=[{"id": "f1", "siteId": "s1"}, {"id": "f2", "siteId": "s2"}],
        fabric_devices={"f2": [{"networkDeviceId": "d2", "deviceRoles": ["EDGE_NODE"]}]},
        members={"s2": ["d2", "d3"]},
    )

    fabric = _run(client, include_underlay=True, fabric_site="Global/Munich")

    asked = [p["fabricId"] for path, p in client.calls if path == FABRIC_DEVICES_PATH]
    member_calls = [path for path, _ in client.calls if path.startswith(MEMBERSHIP + "/")]
    assert asked == ["f2"] and member_calls == [MEMBERSHIP + "/s2"]
    assert [u.device_id for u in fabric.underlay_only] == ["d3"]
    assert len(fabric.sites) == 2  # the site list itself stays whole


def test_the_site_list_is_read_once_for_all_underlay_lookups() -> None:
    client = _client(
        fabric_sites=[{"id": "f1", "siteId": "s1"}, {"id": "f2", "siteId": "s2"}],
        members={"s1": ["d1"], "s2": ["d2"]},
    )

    _run(client, include_underlay=True)

    assert [path for path, _ in client.calls].count(SITE) == 1


def test_a_too_wide_site_is_incomplete_and_the_overlay_survives() -> None:
    client = _client(
        fabric_sites=[{"id": "f1", "siteId": "s1"}],
        fabric_devices={"f1": [{"networkDeviceId": "d1", "deviceRoles": ["EDGE_NODE"]}]},
    )
    service = CatalystCenterFabricService(client, _creds())

    async def too_wide(names, *, include_children=True, sites=None):
        raise CatalystCenterTooManySitesError("covers 120 sites")

    service._sites.device_ids_for_sites = too_wide  # type: ignore[method-assign]
    fabric = asyncio.run(service.read_fabric(include_underlay=True))

    assert [d.device_id for d in fabric.devices] == ["d1"]
    assert fabric.underlay_only == () and fabric.incomplete_sites == ("Global/Berlin",)


def test_a_device_under_nested_fabric_sites_belongs_to_the_most_specific_one() -> None:
    client = _client(
        fabric_sites=[{"id": "f2", "siteId": "s2"}, {"id": "f1", "siteId": "s1"}],
        members={"s1": ["d9"], "s2": ["d9"]},
    )
    service = CatalystCenterFabricService(client, _creds())

    async def members(names, *, include_children=True, sites=None):
        return frozenset({"d9"})

    service._sites.device_ids_for_sites = members  # type: ignore[method-assign]
    # Make s2 the deeper site by name.
    original = client.request

    async def request(creds, method, path, *, params=None, json=None):
        if path == SITE:
            return {
                "response": [
                    {"id": "s1", "siteNameHierarchy": "Global/Berlin"},
                    {"id": "s2", "siteNameHierarchy": "Global/Berlin/HQ"},
                ]
            }
        return await original(creds, method, path, params=params, json=json)

    client.request = request
    fabric = asyncio.run(service.read_fabric(include_underlay=True))

    assert [(u.device_id, u.fabric_site) for u in fabric.underlay_only] == [
        ("d9", "Global/Berlin/HQ")
    ]


def test_a_device_id_outside_the_id_pattern_is_skipped() -> None:
    client = _client(
        fabric_sites=[{"id": "f1", "siteId": "s1"}],
        fabric_devices={
            "f1": [
                {"networkDeviceId": "{braces}", "deviceRoles": ["EDGE_NODE"]},
                {"networkDeviceId": "x" * 65, "deviceRoles": ["EDGE_NODE"]},
                {"networkDeviceId": "ok-1", "deviceRoles": ["EDGE_NODE"]},
            ]
        },
    )

    assert [d.device_id for d in _run(client).devices] == ["ok-1"]


L2 = "/dna/intent/api/v1/sda/layer2VirtualNetworks"


def _vn_client(*, l2_missing: bool = False, l2=None, l3=None):
    client = _client(
        fabric_sites=[{"id": "f1", "siteId": "s1"}],
        vns=l3
        if l3 is not None
        else [
            {"id": "v1", "virtualNetworkName": "CORP", "fabricIds": ["f1"]},
            {"id": "v2", "virtualNetworkName": "INFRA_VN"},  # live shape: not deployed
        ],
    )
    original = client.request

    async def request(creds, method, path, *, params=None, json=None):
        if path == L2:
            if l2_missing:
                raise CatalystCenterNotFoundError("nope")
            return {"response": l2 or []}
        return await original(creds, method, path, params=params, json=json)

    client.request = request
    return client


def test_virtual_networks_carry_ids_sites_and_vlans() -> None:
    client = _vn_client(
        l2=[
            {
                "vlanName": "users",
                "vlanId": "1021",
                "trafficType": "DATA",
                "associatedLayer3VirtualNetworkName": "CORP",
                "fabricId": "f1",
            },
            {"vlanName": ""},
        ]
    )

    found = asyncio.run(CatalystCenterFabricService(client, _creds()).list_virtual_networks())

    assert [(n.name, n.id, n.fabric_sites) for n in found.networks] == [
        ("CORP", "v1", ("Global/Berlin",)),
        ("INFRA_VN", "v2", ()),
    ]
    assert [
        (v.vlan_name, v.vlan_id, v.layer3_virtual_network, v.fabric_site) for v in found.layer2
    ] == [("users", 1021, "CORP", "Global/Berlin")]
    assert found.layer2_available is True


def test_missing_layer2_api_keeps_the_layer3_answer() -> None:
    found = asyncio.run(
        CatalystCenterFabricService(_vn_client(l2_missing=True), _creds()).list_virtual_networks()
    )

    assert len(found.networks) == 2 and found.layer2 == () and found.layer2_available is False


def test_a_missing_fabric_site_api_means_no_sd_access() -> None:
    with pytest.raises(CatalystCenterNotFoundError):
        asyncio.run(
            CatalystCenterFabricService(_client(missing=True), _creds()).list_virtual_networks()
        )

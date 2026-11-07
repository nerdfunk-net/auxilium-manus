"""AciSubnetService: gateway subnets of bridge domains and EPGs, with their VRF."""

from __future__ import annotations

import unittest
from typing import Any

from services.aci.common.exceptions import AciAPIError
from services.aci.credentials import AciCredentials
from services.aci.subnet_service import MAX_SUBNET_ROWS, AciSubnetService

CREDS = AciCredentials(base_url="https://10.10.20.14", username="admin", password="pw")

ROWS: dict[str, list[dict[str, Any]]] = {
    "fvBD": [
        {"dn": "uni/tn-Heroes/BD-Hero_Land", "name": "Hero_Land"},
        {"dn": "uni/tn-Heroes/BD-L2only", "name": "L2only"},
        {"dn": "uni/tn-common/BD-shared_bd", "name": "shared_bd"},
    ],
    "fvRsCtx": [
        {"dn": "uni/tn-Heroes/BD-Hero_Land/rsctx", "tnFvCtxName": "Heroes_Only"},
        {"dn": "uni/tn-common/BD-shared_bd/rsctx", "tnFvCtxName": "default"},
    ],
    "fvRsBd": [
        {"dn": "uni/tn-Heroes/ap-App/epg-web/rsbd", "tnFvBDName": "Hero_Land"},
        {"dn": "uni/tn-Heroes/ap-App/epg-shared/rsbd", "tnFvBDName": "shared_bd"},
    ],
    "fvSubnet": [
        {
            "dn": "uni/tn-Heroes/BD-Hero_Land/subnet-[10.1.1.1/24]",
            "ip": "10.1.1.1/24",
            "scope": "private,shared",
            "virtual": "no",
        },
        {"dn": "uni/tn-Heroes/BD-Hero_Land/subnet-[2001:db8:1::1/64]", "ip": "2001:db8:1::1/64"},
        {
            "dn": "uni/tn-Heroes/ap-App/epg-web/subnet-[10.9.9.1/28]",
            "ip": "10.9.9.1/28",
            "scope": "public",
        },
        {"dn": "uni/tn-common/BD-shared_bd/subnet-[10.200.0.1/24]", "ip": "10.200.0.1/24"},
    ],
}


class FakeClient:
    def __init__(self, rows=None, errors=None) -> None:
        self.rows = ROWS if rows is None else rows
        self.errors = errors or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def query_class(self, credentials, class_name, **kwargs):
        self.calls.append((class_name, kwargs))
        if class_name in self.errors:
            raise self.errors[class_name]
        return [dict(r) for r in self.rows.get(class_name, [])]


def service(client: FakeClient) -> AciSubnetService:
    return AciSubnetService(client, CREDS)  # type: ignore[arg-type]


class SubnetTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_bridge_domain_subnet_with_network_gateway_vrf_and_scope(self) -> None:
        subnets = await service(FakeClient()).list_subnets()
        first = next(s for s in subnets if s.prefix == "10.1.1.0/24")
        self.assertEqual(first.gateway, "10.1.1.1")
        self.assertEqual(
            (first.tenant, first.bridge_domain, first.vrf), ("Heroes", "Hero_Land", "Heroes_Only")
        )
        self.assertEqual((first.owner, first.epg), ("bd", None))
        self.assertEqual(first.scope, ("private", "shared"))

    async def test_ipv6_subnets_are_read_too(self) -> None:
        subnets = await service(FakeClient()).list_subnets()
        v6 = next(s for s in subnets if s.gateway == "2001:db8:1::1")
        self.assertEqual(v6.prefix, "2001:db8:1::/64")

    async def test_an_epg_subnet_takes_the_vrf_of_the_epgs_bridge_domain(self) -> None:
        subnets = await service(FakeClient()).list_subnets()
        epg = next(s for s in subnets if s.prefix == "10.9.9.0/28")
        self.assertEqual(
            (epg.owner, epg.epg, epg.bridge_domain, epg.vrf),
            ("epg", "web", "Hero_Land", "Heroes_Only"),
        )
        self.assertEqual(epg.scope, ("public",))

    async def test_a_bridge_domain_of_the_common_tenant_resolves_from_another_tenant(self) -> None:
        rows = {
            **ROWS,
            "fvSubnet": [
                {
                    "dn": "uni/tn-Heroes/ap-App/epg-shared/subnet-[10.50.0.1/24]",
                    "ip": "10.50.0.1/24",
                }
            ],
        }
        (subnet,) = await service(FakeClient(rows)).list_subnets()
        self.assertEqual((subnet.bridge_domain, subnet.vrf), ("shared_bd", "default"))

    async def test_a_bridge_domain_without_a_vrf_relation_has_no_vrf(self) -> None:
        rows = {**ROWS, "fvRsCtx": []}
        subnets = await service(FakeClient(rows)).list_subnets()
        self.assertTrue(all(s.vrf is None for s in subnets))

    async def test_sorted_by_tenant_then_prefix(self) -> None:
        subnets = await service(FakeClient()).list_subnets()
        keys = [(s.tenant, s.prefix) for s in subnets]
        self.assertEqual(keys, sorted(keys))

    async def test_a_row_that_is_not_a_subnet_dn_or_address_is_skipped(self) -> None:
        rows = {
            **ROWS,
            "fvSubnet": [
                {"dn": "uni/tn-T/out-O/instP-I/extsubnet-[0.0.0.0/0]", "ip": "0.0.0.0/0"},
                {"dn": "uni/tn-T/BD-X/subnet-[not-an-ip]", "ip": "not-an-ip"},
                {"dn": "uni/tn-T/BD-X/subnet-[10.0.0.1/24]", "ip": ""},
            ],
        }
        self.assertEqual(await service(FakeClient(rows)).list_subnets(), ())

    async def test_every_class_is_read_once_with_the_row_limit(self) -> None:
        client = FakeClient()
        await service(client).list_subnets()
        names = [c[0] for c in client.calls]
        self.assertEqual(sorted(names), sorted(set(names)))
        self.assertTrue(all(c[1].get("max_objects") == MAX_SUBNET_ROWS for c in client.calls))

    async def test_an_apic_error_propagates(self) -> None:
        with self.assertRaises(AciAPIError):
            await service(
                FakeClient(errors={"fvSubnet": AciAPIError("down", http_status=503)})
            ).list_subnets()

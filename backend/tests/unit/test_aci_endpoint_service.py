"""AciEndpointService: where an IP or MAC address lives in the fabric (``fvCEp``)."""

from __future__ import annotations

import unittest
from typing import Any

from services.aci.common.exceptions import AciAPIError, AciValidationError
from services.aci.credentials import AciCredentials
from services.aci.endpoint_service import MAX_MATCHES, AciEndpointService, normalize_mac

CREDS = AciCredentials(base_url="https://10.10.20.14", username="admin", password="pw")
MAC = "00:50:56:AA:BB:01"
CEP_DN = f"uni/tn-Heroes/ap-App/epg-web/cep-{MAC}"


def _cep(
    mac: str = MAC, dn: str | None = None, ips=("10.1.1.5",), paths=None, ip: str = "10.1.1.5"
):
    paths = ["topology/pod-1/paths-101/pathep-[eth1/5]"] if paths is None else paths
    return {
        "attributes": {
            "mac": mac,
            "dn": dn or f"uni/tn-Heroes/ap-App/epg-web/cep-{mac}",
            "ip": ip,
            "encap": "vlan-200",
        },
        "children": {
            "fvIp": [{"addr": a} for a in ips],
            "fvRsCEpToPathEp": [{"tDn": p} for p in paths],
        },
    }


class FakeClient:
    def __init__(self, ips=None, ceps=None, errors=None) -> None:
        self.ips = (
            ips if ips is not None else [{"dn": f"{CEP_DN}/ip-[10.1.1.5]", "addr": "10.1.1.5"}]
        )
        self.ceps = ceps if ceps is not None else [_cep()]
        self.errors = errors or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def query_class(self, credentials, class_name, **kwargs):
        self.calls.append((class_name, kwargs))
        if class_name in self.errors:
            raise self.errors[class_name]
        return [dict(r) for r in self.ips]

    async def query_class_tree(self, credentials, class_name, **kwargs):
        self.calls.append((class_name, kwargs))
        if class_name in self.errors:
            raise self.errors[class_name]
        return [dict(r) for r in self.ceps]


def service(client: FakeClient) -> AciEndpointService:
    return AciEndpointService(client, CREDS)  # type: ignore[arg-type]


class NormalizeMacTests(unittest.TestCase):
    def test_the_common_spellings_become_the_apic_form(self) -> None:
        for raw in ("00:50:56:aa:bb:01", "0050.56aa.bb01", "00-50-56-AA-BB-01", "005056aabb01"):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_mac(raw), MAC)

    def test_anything_else_is_not_a_mac(self) -> None:
        for raw in ("", "10.1.1.5", "00:50:56:aa:bb", "zz:50:56:aa:bb:01", 'AA"),or(x'):
            with self.subTest(raw=raw):
                self.assertIsNone(normalize_mac(raw))


class FindByIpTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_ip_resolves_to_endpoint_epg_and_attachment(self) -> None:
        (endpoint,) = await service(FakeClient()).find("10.1.1.5")
        self.assertEqual(
            (endpoint.mac, endpoint.ips, endpoint.encap), (MAC, ("10.1.1.5",), "vlan-200")
        )
        self.assertEqual(
            (endpoint.tenant, endpoint.app_profile, endpoint.epg), ("Heroes", "App", "web")
        )
        self.assertIsNone(endpoint.external_epg)
        (attachment,) = endpoint.attachments
        self.assertEqual(
            (attachment.pod_id, attachment.node_ids, attachment.interface), (1, (101,), "eth1/5")
        )

    async def test_two_steps_the_address_filter_then_the_endpoint_tree(self) -> None:
        client = FakeClient()
        await service(client).find("10.1.1.5")
        (first, ip_kwargs), (second, tree_kwargs) = client.calls
        self.assertEqual((first, second), ("fvIp", "fvCEp"))
        self.assertEqual(ip_kwargs["query_filter"], 'eq(fvIp.addr,"10.1.1.5")')
        self.assertEqual(tree_kwargs["query_filter"], f'eq(fvCEp.dn,"{CEP_DN}")')
        self.assertEqual(tree_kwargs["child_classes"], ("fvIp", "fvRsCEpToPathEp"))

    async def test_several_endpoints_with_one_ip_are_all_returned(self) -> None:
        other = "00:50:56:AA:BB:02"
        client = FakeClient(
            ips=[
                {"dn": f"{CEP_DN}/ip-[10.1.1.5]"},
                {"dn": f"uni/tn-Heroes/ap-App/epg-db/cep-{other}/ip-[10.1.1.5]"},
            ],
            ceps=[_cep(), _cep(other, dn=f"uni/tn-Heroes/ap-App/epg-db/cep-{other}")],
        )
        endpoints = await service(client).find("10.1.1.5")
        self.assertEqual([e.mac for e in endpoints], [MAC, other])
        self.assertIn("or(", client.calls[1][1]["query_filter"])

    async def test_an_unknown_ip_is_an_empty_result_without_a_second_query(self) -> None:
        client = FakeClient(ips=[])
        self.assertEqual(await service(client).find("10.9.9.9"), ())
        self.assertEqual([c[0] for c in client.calls], ["fvIp"])

    async def test_too_many_matches_fail_instead_of_truncating(self) -> None:
        rows = [
            {"dn": f"uni/tn-T/ap-A/epg-E/cep-00:00:00:00:{i // 256:02X}:{i % 256:02X}/ip-[1.1.1.1]"}
            for i in range(MAX_MATCHES + 1)
        ]
        with self.assertRaises(AciAPIError) as caught:
            await service(FakeClient(ips=rows)).find("1.1.1.1")
        self.assertEqual(caught.exception.code, "too_many_objects")

    async def test_a_row_that_is_not_an_endpoint_address_is_ignored(self) -> None:
        client = FakeClient(ips=[{"dn": "uni/tn-T/somewhere/else/ip-[10.1.1.5]"}])
        self.assertEqual(await service(client).find("10.1.1.5"), ())


class FilterSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_dn_with_filter_syntax_is_never_placed_in_a_filter_and_fails_the_lookup(
        self,
    ) -> None:
        evil = f'uni/tn-T"),or(eq(a,"b/ap-A/epg-E/cep-{MAC}/ip-[10.1.1.5]'
        client = FakeClient(ips=[{"dn": evil}])
        # Not an empty "not learned": the fabric did report the address, so the lookup fails.
        with self.assertRaises(AciAPIError) as raised:
            await service(client).find("10.1.1.5")
        self.assertEqual(raised.exception.code, "unsafe_endpoint_dn")
        self.assertEqual([c[0] for c in client.calls], ["fvIp"])  # no endpoint query was built

    async def test_one_unsafe_dn_among_good_ones_fails_instead_of_dropping_it(self) -> None:
        bad = f'uni/tn-T"x/ap-A/epg-E/cep-{MAC[:-2]}02/ip-[10.1.1.5]'
        client = FakeClient(ips=[{"dn": f"{CEP_DN}/ip-[10.1.1.5]"}, {"dn": bad}])
        with self.assertRaises(AciAPIError):
            await service(client).find("10.1.1.5")


class FindByMacTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_mac_goes_straight_to_the_endpoint_query(self) -> None:
        client = FakeClient()
        (endpoint,) = await service(client).find("0050.56aa.bb01")
        self.assertEqual(endpoint.mac, MAC)
        self.assertEqual([c[0] for c in client.calls], ["fvCEp"])
        self.assertEqual(client.calls[0][1]["query_filter"], f'eq(fvCEp.mac,"{MAC}")')


class ShapeTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_vpc_path_names_both_nodes(self) -> None:
        cep = _cep(paths=["topology/pod-1/protpaths-101-102/pathep-[vpc_web]"])
        (endpoint,) = await service(FakeClient(ceps=[cep])).find("10.1.1.5")
        attachment = endpoint.attachments[0]
        self.assertEqual((attachment.node_ids, attachment.interface), ((101, 102), "vpc_web"))

    async def test_an_external_epg_endpoint_has_no_application_epg(self) -> None:
        dn = f"uni/tn-Heroes/out-Internet/instP-all/cep-{MAC}"
        (endpoint,) = await service(FakeClient(ceps=[_cep(dn=dn)])).find(MAC)
        self.assertEqual((endpoint.epg, endpoint.app_profile), (None, None))
        self.assertEqual(endpoint.external_epg, "Internet/all")
        self.assertEqual(endpoint.tenant, "Heroes")

    async def test_ips_combine_the_primary_and_the_children_without_duplicates(self) -> None:
        cep = _cep(ips=("10.1.1.6", "10.1.1.5"), ip="10.1.1.5")
        (endpoint,) = await service(FakeClient(ceps=[cep])).find(MAC)
        self.assertEqual(endpoint.ips, ("10.1.1.5", "10.1.1.6"))

    async def test_an_unset_primary_ip_is_not_listed(self) -> None:
        cep = _cep(ips=(), ip="0.0.0.0")
        (endpoint,) = await service(FakeClient(ceps=[cep])).find(MAC)
        self.assertEqual(endpoint.ips, ())

    async def test_an_endpoint_without_a_path_has_no_attachment(self) -> None:
        (endpoint,) = await service(FakeClient(ceps=[_cep(paths=[])])).find(MAC)
        self.assertEqual(endpoint.attachments, ())

    async def test_a_path_of_another_shape_is_skipped(self) -> None:
        (endpoint,) = await service(FakeClient(ceps=[_cep(paths=["uni/vmmp-VMware/dom-x"])])).find(
            MAC
        )
        self.assertEqual(endpoint.attachments, ())


class ErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_something_that_is_neither_ip_nor_mac_is_rejected_before_any_request(
        self,
    ) -> None:
        client = FakeClient()
        for raw in ("", "leaf-1", "10.1.1.0/24", "2001:db8::1", 'x"),or(eq(a,"b'):
            with self.subTest(raw=raw), self.assertRaises(AciValidationError):
                await service(client).find(raw)
        self.assertEqual(client.calls, [])

    async def test_an_apic_error_propagates(self) -> None:
        with self.assertRaises(AciAPIError):
            await service(FakeClient(errors={"fvIp": AciAPIError("down", http_status=503)})).find(
                "10.1.1.5"
            )

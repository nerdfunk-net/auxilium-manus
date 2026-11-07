"""AciEndpointService: listing by tenant / profile / EPG, VRF and BD of an endpoint, history."""

from __future__ import annotations

import unittest
from typing import Any

from services.aci.common.exceptions import AciAPIError, AciValidationError
from services.aci.credentials import AciCredentials
from services.aci.endpoint_service import MAX_EVENTS, AciEndpointService

CREDS = AciCredentials(base_url="https://10.10.20.14", username="admin", password="pw")
MAC = "00:50:56:AA:BB:01"
DN = f"uni/tn-T/ap-AP/epg-web/cep-{MAC}"


def _cep(mac: str = MAC, **attrs: Any) -> dict[str, Any]:
    return {
        "attributes": {
            "mac": mac,
            "dn": f"uni/tn-T/ap-AP/epg-web/cep-{mac}",
            "encap": "vlan-10",
            "vrfDn": "uni/tn-T/ctx-v1",
            "bdDn": "uni/tn-T/BD-bd1",
            "esgUsegDn": "",
            "modTs": "2026-11-07T12:00:00.000+00:00",
            **attrs,
        },
        "children": {
            "fvIp": [
                {
                    "addr": "10.1.1.5",
                    "createTs": "2026-11-06T08:00:00.000+00:00",
                    "modTs": "2026-11-07T09:00:00.000+00:00",
                },
                {"addr": "10.1.1.6", "createTs": "1970-01-01T00:00:00.000+00:00", "modTs": ""},
            ],
            "fvRsCEpToPathEp": [{"tDn": "topology/pod-1/protpaths-101-102/pathep-[vpc1]"}],
        },
    }


class FakeClient:
    def __init__(self, ceps=None, leaf=None, events=None, fail_leaf=(), fail_get=False) -> None:
        self.ceps = [_cep()] if ceps is None else ceps
        self.leaf = leaf if leaf is not None else {}
        self.events = events or {"eventRecord": [], "faultRecord": []}
        self.fail_leaf, self.fail_get = set(fail_leaf), fail_get
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def query_class(self, credentials, class_name, **kwargs):
        self.calls.append((class_name, kwargs))
        return [{"dn": f"{DN}/ip-[10.1.1.5]", "addr": "10.1.1.5"}]

    async def query_class_tree(self, credentials, class_name, **kwargs):
        self.calls.append((class_name, kwargs))
        return [dict(r) for r in self.ceps]

    async def query_node_class(self, credentials, pod, node, class_name, **kwargs):
        self.calls.append((f"node-{node}:{class_name}", kwargs))
        if node in self.fail_leaf:
            raise AciAPIError("down", code="transport")
        return list(self.leaf.get(node, []))

    async def get(self, credentials, path, *, params=None):
        self.calls.append((path, params or {}))
        if self.fail_get:
            raise AciAPIError("down", code="transport")
        cls = path.rsplit("/", 1)[-1].removesuffix(".json")
        return {"imdata": [{cls: {"attributes": a}} for a in self.events.get(cls, [])]}


def service(client: FakeClient) -> AciEndpointService:
    return AciEndpointService(client, CREDS)  # type: ignore[arg-type]


class EndpointAttributesTests(unittest.IsolatedAsyncioTestCase):
    async def test_vrf_bridge_domain_and_esg_are_read_from_the_endpoint(self) -> None:
        esg = _cep(esgUsegDn="uni/tn-T/ap-AP/esg-gold")
        (endpoint,) = await service(FakeClient(ceps=[esg])).find(MAC)
        self.assertEqual(
            (endpoint.vrf, endpoint.bridge_domain, endpoint.esg), ("T/v1", "T/bd1", "T/AP/gold")
        )

    async def test_an_endpoint_without_those_attributes_has_none(self) -> None:
        bare = _cep(vrfDn="", bdDn="")
        (endpoint,) = await service(FakeClient(ceps=[bare])).find(MAC)
        self.assertEqual((endpoint.vrf, endpoint.bridge_domain, endpoint.esg), (None, None, None))


class ListEndpointsTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_filter_names_the_tenant_profile_and_epg(self) -> None:
        for kwargs, needle in (
            ({"tenant": "T"}, "/tn-T/"),
            ({"tenant": "T", "app_profile": "AP"}, "/tn-T/ap-AP/"),
            ({"tenant": "T", "app_profile": "AP", "epg": "web"}, "/tn-T/ap-AP/epg-web/"),
        ):
            client = FakeClient()
            found = await service(client).list_endpoints(**kwargs)
            self.assertEqual(len(found), 1)
            name, call = client.calls[0]
            self.assertEqual(name, "fvCEp")
            self.assertEqual(call["query_filter"], f'wcard(fvCEp.dn,"{needle}")')

    async def test_names_with_filter_syntax_are_refused_before_any_request(self) -> None:
        for bad in ('x"),or(eq(a,"b', "a b", "x/y", "", "(", "a" * 65):
            client = FakeClient()
            with self.subTest(name=bad), self.assertRaises(AciValidationError):
                await service(client).list_endpoints(tenant=bad)
            self.assertEqual(client.calls, [])
        with self.assertRaises(AciValidationError):
            await service(FakeClient()).list_endpoints(tenant="T", epg="web")

    async def test_too_many_endpoints_propagate_instead_of_truncating(self) -> None:
        class Big(FakeClient):
            async def query_class_tree(self, *a, **k):
                raise AciAPIError("more", code="too_many_objects")

        with self.assertRaises(AciAPIError):
            await service(Big()).list_endpoints(tenant="T")


LEAF_ROW = {
    "ifId": "po1",
    "createTs": "2026-11-05T10:00:00.000+00:00",
    "modTs": "2026-11-07T11:00:00.000+00:00",
    "flags": "local",
}


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_timestamps_of_the_endpoint_its_addresses_and_each_leaf_of_the_vpc(self) -> None:
        client = FakeClient(leaf={101: [LEAF_ROW], 102: [{**LEAF_ROW, "ifId": "po2"}]})
        (history,) = await service(client).history("10.1.1.5")
        self.assertEqual(history.last_changed, "2026-11-07T12:00:00.000+00:00")
        by_ip = {r.address: r for r in history.ips}
        self.assertEqual(by_ip["10.1.1.5"].learned_at, "2026-11-06T08:00:00.000+00:00")
        self.assertIsNone(by_ip["10.1.1.6"].learned_at)  # the epoch is "unknown", not a date
        self.assertEqual(
            [(r.node_id, r.interface, r.first_seen) for r in history.leaf_records],
            [
                (101, "po1", "2026-11-05T10:00:00.000+00:00"),
                (102, "po2", "2026-11-05T10:00:00.000+00:00"),
            ],
        )
        self.assertEqual((history.leaf_records_failed, history.events_unavailable), (0, False))

    async def test_a_failing_leaf_is_counted_not_hidden(self) -> None:
        client = FakeClient(leaf={101: [LEAF_ROW]}, fail_leaf=[102])
        (history,) = await service(client).history(MAC)
        self.assertEqual(len(history.leaf_records), 1)
        self.assertEqual(history.leaf_records_failed, 1)

    async def test_events_and_faults_are_merged_newest_first(self) -> None:
        events = {
            "eventRecord": [
                {
                    "created": "2026-11-07T10:00:00.000+00:00",
                    "code": "E1",
                    "severity": "info",
                    "descr": "moved",
                }
            ],
            "faultRecord": [
                {
                    "created": "2026-11-07T11:00:00.000+00:00",
                    "code": "F2",
                    "severity": "major",
                    "descr": "dup ip",
                }
            ],
        }
        (history,) = await service(FakeClient(events=events)).history(MAC)
        self.assertEqual(
            [(e.kind, e.code) for e in history.events], [("fault", "F2"), ("event", "E1")]
        )

    async def test_a_failing_log_read_is_flagged(self) -> None:
        (history,) = await service(FakeClient(fail_get=True)).history(MAC)
        self.assertTrue(history.events_unavailable)

    async def test_only_validated_values_reach_the_log_filters(self) -> None:
        client = FakeClient()
        await service(client).history("10.1.1.5")
        queries = [c for name, c in client.calls if name.endswith("Record.json")]
        self.assertEqual(len(queries), 2)
        for params in queries:
            self.assertEqual(params["page-size"], MAX_EVENTS)
            self.assertIn(MAC, params["query-target-filter"])
            self.assertIn("10.1.1.5", params["query-target-filter"])
            self.assertTrue(params["order-by"].endswith("created|desc"))

    async def test_an_unknown_address_has_no_history_and_a_bad_one_is_refused(self) -> None:
        client = FakeClient(ceps=[])
        self.assertEqual(await service(client).history(MAC), ())
        with self.assertRaises(AciValidationError):
            await service(FakeClient()).history("not-an-address")

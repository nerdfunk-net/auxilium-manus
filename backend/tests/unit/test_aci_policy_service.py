"""AciPolicyService: tenant policy (EPGs, contracts, subjects, filters) read once per APIC."""

from __future__ import annotations

import unittest
from typing import Any

from services.aci.common.exceptions import AciAPIError
from services.aci.credentials import AciCredentials
from services.aci.policy_service import MAX_POLICY_ROWS, AciPolicyService

CREDS = AciCredentials(base_url="https://10.10.20.14", username="admin", password="pw")

WEB = "uni/tn-Heroes/ap-App/epg-web"
EXT = "uni/tn-Heroes/out-Internet/instP-all"
DB = "uni/tn-Heroes/ap-App/epg-db"
ROWS: dict[str, list[dict[str, Any]]] = {
    "fvAEPg": [
        {"dn": WEB, "name": "web", "pcTag": "49154"},
        {"dn": DB, "name": "db", "pcTag": "32772"},
        {"dn": "uni/tn-Other/ap-X/epg-y", "name": "y", "pcTag": "5"},
    ],
    "fvRsBd": [{"dn": f"{WEB}/rsbd", "tnFvBDName": "Hero_Land"}],
    "fvRsProv": [
        {"dn": f"{DB}/rsprov-sql", "tnVzBrCPName": "sql"},
        {"dn": f"{DB}/rsprov-shared", "tnVzBrCPName": "shared"},
        {"dn": f"{EXT}/rsprov-shared", "tnVzBrCPName": "shared"},
    ],
    "fvRsCons": [
        {"dn": f"{WEB}/rscons-sql", "tnVzBrCPName": "sql"},
        {"dn": f"{WEB}/rscons-shared", "tnVzBrCPName": "shared"},
        {"dn": f"{EXT}/rscons-sql", "tnVzBrCPName": "sql"},
    ],
    "vzBrCP": [
        {"dn": "uni/tn-Heroes/brc-sql", "name": "sql", "scope": "context", "prio": "level3"},
        {
            "dn": "uni/tn-common/brc-shared",
            "name": "shared",
            "scope": "global",
            "prio": "unspecified",
        },
    ],
    "vzSubj": [
        {"dn": "uni/tn-Heroes/brc-sql/subj-s1", "name": "s1"},
        {"dn": "uni/tn-common/brc-shared/subj-any", "name": "any"},
    ],
    "vzRsSubjFiltAtt": [
        {"dn": "uni/tn-Heroes/brc-sql/subj-s1/rssubjFiltAtt-sqlflt", "tnVzFilterName": "sqlflt"},
        {
            "dn": "uni/tn-common/brc-shared/subj-any/rssubjFiltAtt-default",
            "tnVzFilterName": "default",
        },
    ],
    "l3extOut": [
        {"dn": "uni/tn-Heroes/out-Internet", "name": "Internet"},
        {"dn": "uni/tn-Heroes/out-Other", "name": "Other"},
    ],
    "l3extRsEctx": [{"dn": "uni/tn-Heroes/out-Internet/rsectx", "tnFvCtxName": "Heroes_Only"}],
    "l3extInstP": [
        {"dn": f"{EXT}", "name": "all", "pcTag": "15", "prio": "unspecified"},
    ],
    "l3extSubnet": [
        {
            "dn": f"{EXT}/extsubnet-[0.0.0.0/0]",
            "ip": "0.0.0.0/0",
            "scope": "import-security,shared-rtctrl",
            "aggregate": "",
        }
    ],
    "l3extRsNodeL3OutAtt": [
        {
            "dn": "uni/tn-Heroes/out-Internet/lnodep-np/rsnodeL3OutAtt-[topology/pod-1/node-101]",
            "tDn": "topology/pod-1/node-101",
            "rtrId": "1.1.1.1",
        }
    ],
    "l3extRsPathL3OutAtt": [
        {
            "dn": (
                "uni/tn-Heroes/out-Internet/lnodep-np/lifp-ip/"
                "rspathL3OutAtt-[topology/pod-1/paths-101/pathep-[eth1/10]]"
            ),
            "tDn": "topology/pod-1/paths-101/pathep-[eth1/10]",
            "addr": "192.0.2.1/30",
            "ifInstT": "l3-port",
            "encap": "unknown",
            "mtu": "9000",
        },
        {
            "dn": (
                "uni/tn-Heroes/out-Other/lnodep-np/lifp-ip/"
                "rspathL3OutAtt-[topology/pod-1/protpaths-102-103/pathep-[vpc1]]"
            ),
            "tDn": "topology/pod-1/protpaths-102-103/pathep-[vpc1]",
            "addr": "198.51.100.1/29",
            "ifInstT": "ext-svi",
            "encap": "vlan-100",
        },
    ],
    "bgpExtP": [{"dn": "uni/tn-Heroes/out-Internet/bgpExtP"}],
    "ospfExtP": [{"dn": "uni/tn-Heroes/out-Other/ospfExtP"}],
    "vzEntry": [
        {
            "dn": "uni/tn-Heroes/flt-sqlflt/e-tcp",
            "name": "tcp",
            "etherT": "ip",
            "prot": "tcp",
            "dFromPort": "1433",
            "dToPort": "1433",
            "sFromPort": "unspecified",
            "sToPort": "unspecified",
            "stateful": "yes",
            "applyToFrag": "no",
            "tcpRules": "",
        },
        {"dn": "uni/tn-common/flt-default/e-any", "name": "any", "etherT": "unspecified"},
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


def service(client: FakeClient) -> AciPolicyService:
    return AciPolicyService(client, CREDS)  # type: ignore[arg-type]


class SnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_epg_with_its_provided_and_consumed_contracts(self) -> None:
        snapshot = await service(FakeClient()).snapshot()
        epgs, _, _ = snapshot.for_device({WEB, DB}, 1, 999)
        db, web = epgs
        self.assertEqual(
            (web.tenant, web.app_profile, web.epg, web.pc_tag), ("Heroes", "App", "web", "49154")
        )
        self.assertEqual(web.bridge_domain, "Hero_Land")
        self.assertEqual(web.consumed, ("Heroes/sql", "common/shared"))
        self.assertEqual(web.provided, ())
        self.assertEqual(db.provided, ("Heroes/sql", "common/shared"))

    async def test_a_contract_with_subjects_filters_entries_and_both_sides(self) -> None:
        snapshot = await service(FakeClient()).snapshot()
        _, contracts, _ = snapshot.for_device({WEB}, 1, 999)
        sql = next(c for c in contracts if c.name == "sql")
        self.assertEqual((sql.tenant, sql.scope, sql.priority), ("Heroes", "context", "level3"))
        (subject,) = sql.subjects
        (flt,) = subject.filters
        self.assertEqual((subject.name, flt.name, flt.tenant), ("s1", "sqlflt", "Heroes"))
        (entry,) = flt.entries
        self.assertEqual((entry.ether_type, entry.protocol), ("ip", "tcp"))
        self.assertEqual((entry.destination_port_from, entry.destination_port_to), ("1433", "1433"))
        self.assertIsNone(entry.source_port_from)  # "unspecified" is not a value
        self.assertEqual(sql.provider_epgs, (DB,))
        # An external EPG consumes it too: it sorts after the application EPG.
        self.assertEqual(sql.consumer_epgs, (WEB, EXT))

    async def test_a_filter_of_the_common_tenant_is_found_from_another_tenant(self) -> None:
        snapshot = await service(FakeClient()).snapshot()
        _, contracts, _ = snapshot.for_device({WEB}, 1, 999)
        shared = next(c for c in contracts if c.name == "shared")
        self.assertEqual(shared.tenant, "common")
        (flt,) = shared.subjects[0].filters
        self.assertEqual((flt.name, flt.tenant, len(flt.entries)), ("default", "common", 1))

    async def test_only_the_contracts_of_the_given_epgs_are_returned(self) -> None:
        snapshot = await service(FakeClient()).snapshot()
        epgs, contracts, _ = snapshot.for_device({"uni/tn-Other/ap-X/epg-y"}, 1, 999)
        self.assertEqual([e.epg for e in epgs], ["y"])
        self.assertEqual(contracts, ())

    async def test_an_epg_the_policy_does_not_know_is_reported_with_its_parts(self) -> None:
        epgs, _, _ = (await service(FakeClient()).snapshot()).for_device(
            {"uni/tn-T/ap-A/epg-gone"}, 1, 999
        )
        self.assertEqual(
            [(e.tenant, e.app_profile, e.epg, e.provided) for e in epgs], [("T", "A", "gone", ())]
        )

    async def test_a_contract_that_does_not_exist_is_kept_by_name(self) -> None:
        rows = {**ROWS, "vzBrCP": []}
        epgs, contracts, _ = (await service(FakeClient(rows)).snapshot()).for_device({WEB}, 1, 999)
        self.assertEqual(epgs[0].consumed, ("Heroes/shared", "Heroes/sql"))
        self.assertEqual(contracts, ())

    async def test_every_class_is_read_once_with_the_row_limit(self) -> None:
        client = FakeClient()
        await service(client).snapshot()
        names = [c[0] for c in client.calls]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(c[1].get("max_objects") == MAX_POLICY_ROWS for c in client.calls))

    async def test_an_apic_error_fails_the_snapshot(self) -> None:
        with self.assertRaises(AciAPIError):
            await service(
                FakeClient(errors={"vzEntry": AciAPIError("down", http_status=503)})
            ).snapshot()

    async def test_the_result_is_not_mutated_across_calls(self) -> None:
        snapshot = await service(FakeClient()).snapshot()
        first = snapshot.for_device({WEB}, 1, 101)
        self.assertEqual(first, snapshot.for_device({WEB}, 1, 101))


class L3OutTests(unittest.IsolatedAsyncioTestCase):
    async def _l3outs(self, node: int, rows=None):
        snapshot = await service(FakeClient(rows)).snapshot()
        return snapshot.for_device(set(), 1, node)

    async def test_an_l3out_on_the_node_with_vrf_protocols_nodes_and_interfaces(self) -> None:
        _, _, (out,) = await self._l3outs(101)
        self.assertEqual((out.tenant, out.name, out.vrf), ("Heroes", "Internet", "Heroes_Only"))
        self.assertEqual(out.protocols, ("bgp",))
        self.assertEqual([(n.node_id, n.router_id) for n in out.nodes], [(101, "1.1.1.1")])
        (iface,) = out.interfaces
        self.assertEqual((iface.pod_id, iface.node_ids, iface.interface), (1, (101,), "eth1/10"))
        self.assertEqual(
            (iface.address, iface.type, iface.mtu), ("192.0.2.1/30", "l3-port", "9000")
        )
        self.assertIsNone(iface.encap)  # "unknown" is not a value

    async def test_an_external_epg_with_subnets_scope_and_contracts(self) -> None:
        _, _, (out,) = await self._l3outs(101)
        (ext,) = out.external_epgs
        self.assertEqual((ext.name, ext.epg_dn, ext.pc_tag), ("all", EXT, "15"))
        self.assertEqual((ext.provided, ext.consumed), (("common/shared",), ("Heroes/sql",)))
        (subnet,) = ext.subnets
        self.assertEqual(subnet.ip, "0.0.0.0/0")
        self.assertEqual(subnet.scope, ("import-security", "shared-rtctrl"))

    async def test_a_vpc_path_puts_the_l3out_on_both_nodes(self) -> None:
        for node in (102, 103):
            with self.subTest(node=node):
                _, _, (out,) = await self._l3outs(node)
                self.assertEqual(out.name, "Other")
                self.assertEqual(out.interfaces[0].node_ids, (102, 103))
                self.assertEqual(out.protocols, ("ospf",))

    async def test_a_node_without_an_l3out_gets_none(self) -> None:
        self.assertEqual((await self._l3outs(999))[2], ())

    async def test_the_contracts_of_the_external_epgs_come_with_the_node(self) -> None:
        _, contracts, _ = await self._l3outs(101)
        self.assertEqual(
            [(c.tenant, c.name) for c in contracts], [("Heroes", "sql"), ("common", "shared")]
        )

    async def test_external_epgs_are_listed_as_contract_sides_but_not_as_application_epgs(
        self,
    ) -> None:
        snapshot = await service(FakeClient()).snapshot()
        self.assertNotIn(EXT, snapshot.epgs)
        shared = snapshot.contracts[("common", "shared")]
        self.assertIn(EXT, shared.provider_epgs)

    async def test_an_l3out_without_a_vrf_or_nodes_keeps_what_it_has(self) -> None:
        rows = {**ROWS, "l3extRsEctx": [], "l3extRsNodeL3OutAtt": [], "l3extRsPathL3OutAtt": []}
        snapshot = await service(FakeClient(rows)).snapshot()
        # No node is known any more, so no switch carries it.
        self.assertEqual(snapshot.for_device(set(), 1, 101)[2], ())

    async def test_a_node_attachment_alone_puts_the_l3out_on_the_node(self) -> None:
        rows = {**ROWS, "l3extRsPathL3OutAtt": []}
        out = (await self._l3outs(101, rows))[2]
        self.assertEqual([o.name for o in out], ["Internet"])
        self.assertEqual(out[0].interfaces, ())

    async def test_an_interface_path_alone_puts_the_l3out_on_the_node(self) -> None:
        rows = {**ROWS, "l3extRsNodeL3OutAtt": []}
        out = (await self._l3outs(101, rows))[2]
        self.assertEqual([o.name for o in out], ["Internet"])
        self.assertEqual(out[0].nodes, ())


FLOW_ROWS: dict[str, list[dict[str, Any]]] = {
    **ROWS,
    "fvAEPg": [
        {
            "dn": WEB,
            "name": "web",
            "pcTag": "49154",
            "prefGrMemb": "include",
            "pcEnfPref": "enforced",
        },
        {
            "dn": DB,
            "name": "db",
            "pcTag": "32772",
            "prefGrMemb": "exclude",
            "pcEnfPref": "unenforced",
        },
    ],
    "l3extInstP": [{"dn": EXT, "name": "all", "pcTag": "15", "prefGrMemb": "include"}],
    "fvCtx": [
        {"dn": "uni/tn-Heroes/ctx-Heroes_Only", "pcEnfPref": "enforced"},
        {"dn": "uni/tn-Heroes/ctx-Open", "pcEnfPref": "unenforced"},
    ],
    "vzAny": [
        {"dn": "uni/tn-Heroes/ctx-Heroes_Only/any", "prefGrMemb": "enabled"},
        {"dn": "uni/tn-Heroes/ctx-Open/any", "prefGrMemb": "disabled"},
    ],
    "vzRsAnyToProv": [
        {"dn": "uni/tn-Heroes/ctx-Heroes_Only/any/rsanyToProv-sql", "tnVzBrCPName": "sql"},
    ],
    "vzRsAnyToCons": [
        {"dn": "uni/tn-Heroes/ctx-Heroes_Only/any/rsanyToCons-shared", "tnVzBrCPName": "shared"},
    ],
    "fvRsProtBy": [{"dn": f"{DB}/rsprotBy-block", "tnVzTabooName": "block"}],
}


class FlowFactsTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_plain_snapshot_reads_no_flow_classes_and_has_no_flow_facts(self) -> None:
        client = FakeClient(FLOW_ROWS)
        snapshot = await service(client).snapshot()
        self.assertNotIn("fvCtx", [c[0] for c in client.calls])
        self.assertEqual((snapshot.vrfs, snapshot.flags), ({}, {}))

    async def test_vrf_enforcement_preferred_group_and_vzany_contracts(self) -> None:
        client = FakeClient(FLOW_ROWS)
        snapshot = await service(client).snapshot(with_flow=True)
        self.assertEqual(len(client.calls), 17 + 5)
        closed = snapshot.vrfs[("Heroes", "Heroes_Only")]
        self.assertEqual(
            (closed.enforced, closed.preferred_group, closed.any_provided, closed.any_consumed),
            (True, True, ("Heroes/sql",), ("common/shared",)),  # "shared" resolves to common
        )
        open_vrf = snapshot.vrfs[("Heroes", "Open")]
        self.assertEqual((open_vrf.enforced, open_vrf.preferred_group), (False, False))

    async def test_epg_preferred_group_isolation_and_taboo(self) -> None:
        snapshot = await service(FakeClient(FLOW_ROWS)).snapshot(with_flow=True)
        web, db, ext = snapshot.flags[WEB], snapshot.flags[DB], snapshot.flags[EXT]
        self.assertEqual((web.preferred_group, web.isolated, web.taboo), (True, True, ()))
        self.assertEqual((db.preferred_group, db.isolated, db.taboo), (False, False, ("block",)))
        self.assertTrue(ext.preferred_group)
        # The contract snapshot itself is the same as without the flow reads.
        plain = await service(FakeClient(FLOW_ROWS)).snapshot()
        self.assertEqual(snapshot.contracts, plain.contracts)
        self.assertEqual(snapshot.epgs, plain.epgs)

    async def test_an_unreadable_flow_class_fails_the_snapshot(self) -> None:
        client = FakeClient(FLOW_ROWS, errors={"fvCtx": AciAPIError("down")})
        with self.assertRaises(AciAPIError):
            await service(client).snapshot(with_flow=True)

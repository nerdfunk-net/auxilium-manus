"""The ``epgs`` and ``contracts`` facts of the ACI details service."""

from __future__ import annotations

import unittest
from typing import Any

from services.aci.common.exceptions import AciAPIError, AciValidationError
from services.aci.details_service import MAX_RULE_ROWS
from tests.unit.test_aci_details_service import leaf_client, service

# Synthetic: the sandbox leaf has no zoning rules, so the shape follows the documented MIT
# (``actrlRule`` dn ``.../sys/actrl/scope-<vrf>/rule-<vrf>-s-<src>-d-<dst>-f-<filter>``).
RULE = {
    "dn": "topology/pod-1/node-101/sys/actrl/scope-2359296/rule-2359296-s-49154-d-32772-f-5",
    "sPcTag": "49154",
    "dPcTag": "32772",
    "fltId": "5",
    "action": "permit",
    "direction": "bi-dir",
    "prio": "fully_qual",
    "operSt": "enabled",
    "scopeId": "2359296",
}
ENTRY = {
    "dn": "topology/pod-1/node-101/sys/actrl/scope-2359296/flt-5/ent-0",
    "etherT": "ip",
    "prot": "tcp",
    "sFromPort": "unspecified",
    "sToPort": "unspecified",
    "dFromPort": "80",
    "dToPort": "443",
    "stateful": "no",
}


def with_rules(*rules: dict[str, Any], entries: tuple[dict[str, Any], ...] = ()):
    return leaf_client(data={"actrlRule": list(rules), "actrlEntry": list(entries)})


class EpgTests(unittest.IsolatedAsyncioTestCase):
    async def test_epgs_with_tenant_profile_tag_encap_bridge_domain_and_vrf(self) -> None:
        epgs = await service(leaf_client()).get_epgs(1, 101)
        web = next(e for e in epgs if e.epg == "web")
        self.assertEqual(
            (web.tenant, web.app_profile, web.epg), ("Heroes", "Save_The_Planet", "web")
        )
        self.assertEqual(web.epg_dn, "uni/tn-Heroes/ap-Save_The_Planet/epg-web")
        self.assertEqual((web.pc_tag, web.encap, web.encap_vlan), ("49154", "vlan-200", 200))
        self.assertEqual((web.bridge_domain, web.vrf), ("Heroes:Hero_Land", "Heroes:Heroes_Only"))

    async def test_sorted_by_tenant_profile_and_epg(self) -> None:
        epgs = await service(leaf_client()).get_epgs(1, 101)
        keys = [(e.tenant, e.app_profile, e.epg) for e in epgs]
        self.assertEqual(keys, sorted(keys))

    async def test_an_epg_dn_of_another_shape_keeps_the_row_without_the_parts(self) -> None:
        row = {
            "dn": "topology/pod-1/node-101/sys/ctx-[vxlan-1]/bd-[vxlan-2]/vlan-[vlan-7]",
            "name": "x",
            "epgDn": "uni/tn-T/out-O/instP-I",
            "encap": "vlan-7",
            "pcTag": "10",
        }
        epgs = await service(leaf_client(data={"vlanCktEp": [row]})).get_epgs(1, 101)
        self.assertEqual(len(epgs), 1)
        self.assertEqual((epgs[0].tenant, epgs[0].app_profile, epgs[0].epg), ("T", None, None))
        self.assertEqual(epgs[0].epg_dn, "uni/tn-T/out-O/instP-I")

    async def test_an_error_reading_the_circuits_fails_the_fact(self) -> None:
        with self.assertRaises(AciAPIError):
            await service(
                leaf_client(errors={"vlanCktEp": AciAPIError("down", http_status=503)})
            ).get_epgs(1, 101)

    async def test_an_unknown_bridge_domain_keeps_the_row(self) -> None:
        epgs = await service(leaf_client(data={"l2BD": [], "l3Ctx": []})).get_epgs(1, 101)
        self.assertEqual(len(epgs), 3)
        self.assertTrue(all(e.bridge_domain is None and e.vrf is None for e in epgs))


class ContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_rule_with_scope_tags_filter_action_and_epg_names(self) -> None:
        contracts = await service(with_rules(RULE)).get_contracts(1, 101)
        (rule,) = contracts.rules
        self.assertEqual((rule.scope, rule.filter_id), ("2359296", "5"))
        self.assertEqual((rule.source_pc_tag, rule.destination_pc_tag), ("49154", "32772"))
        self.assertEqual(
            (rule.source_epg, rule.destination_epg),
            ("Heroes:Save_The_Planet:web", "SnV:Chaos:Web"),
        )
        self.assertEqual(
            (rule.action, rule.direction, rule.priority, rule.state),
            ("permit", "bi-dir", "fully_qual", "enabled"),
        )

    async def test_tags_and_filter_are_read_from_the_dn_when_the_attributes_are_missing(
        self,
    ) -> None:
        bare = {"dn": RULE["dn"], "action": "deny"}
        (rule,) = (await service(with_rules(bare)).get_contracts(1, 101)).rules
        self.assertEqual(
            (rule.source_pc_tag, rule.destination_pc_tag, rule.filter_id), ("49154", "32772", "5")
        )
        self.assertEqual(rule.scope, "2359296")

    async def test_an_unknown_tag_has_no_epg_name(self) -> None:
        other = {**RULE, "sPcTag": "15", "dn": RULE["dn"].replace("s-49154", "s-15")}
        (rule,) = (await service(with_rules(other)).get_contracts(1, 101)).rules
        self.assertEqual((rule.source_pc_tag, rule.source_epg), ("15", None))

    async def test_filter_entries_come_with_their_filter_id(self) -> None:
        contracts = await service(with_rules(RULE, entries=(ENTRY,))).get_contracts(1, 101)
        (entry,) = contracts.filters
        self.assertEqual((entry.filter_id, entry.ether_type, entry.protocol), ("5", "ip", "tcp"))
        self.assertEqual((entry.destination_port_from, entry.destination_port_to), ("80", "443"))
        self.assertIsNone(entry.source_port_from)  # "unspecified" is not a value
        self.assertEqual(entry.stateful, "no")

    async def test_a_switch_without_zoning_rules_gives_empty_lists(self) -> None:
        gone = AciValidationError("unresolved class for actrlRule", http_status=400)
        contracts = await service(
            leaf_client(errors={"actrlRule": gone, "actrlEntry": gone})
        ).get_contracts(1, 101)
        self.assertEqual((contracts.rules, contracts.filters), ((), ()))

    async def test_other_errors_fail_the_fact(self) -> None:
        with self.assertRaises(AciValidationError):
            await service(
                leaf_client(errors={"actrlRule": AciValidationError("rejected", http_status=400)})
            ).get_contracts(1, 101)

    async def test_the_rule_limit_is_passed_to_the_client(self) -> None:
        client = with_rules(RULE)
        await service(client).get_contracts(1, 101)
        limits = {c[3]: c[4].get("max_objects") for c in client.calls if c[0] == "class"}
        self.assertEqual(limits["actrlRule"], MAX_RULE_ROWS)

    async def test_rules_are_sorted_by_scope_then_tags_then_filter(self) -> None:
        second = {**RULE, "dn": RULE["dn"].replace("s-49154", "s-1"), "sPcTag": "1"}
        rules = (await service(with_rules(RULE, second)).get_contracts(1, 101)).rules
        self.assertEqual([r.source_pc_tag for r in rules], ["1", "49154"])

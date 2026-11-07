"""Can host A reach host B on a port: the rules of ``assess_flow`` and the party resolution."""

from __future__ import annotations

import pytest

from models.aci_endpoint import AciEndpoint
from models.aci_flow import AciFlowParty
from models.aci_policy import (
    AciEpgFlags,
    AciExternalEpg,
    AciExternalSubnet,
    AciPolicyContract,
    AciPolicyEpg,
    AciPolicyFilter,
    AciPolicyFilterEntry,
    AciPolicyL3Out,
    AciPolicySubject,
    AciVrfPolicy,
)
from services.aci.connectivity import (
    assess_flow,
    describe_entry,
    external_party,
    parties,
    party_for_endpoint,
)
from services.aci.policy_service import AciPolicySnapshot

VRF = "T/v1"


def _dn(ap: str, epg: str, tenant: str = "T") -> str:
    return f"uni/tn-{tenant}/ap-{ap}/epg-{epg}"


def _entry(proto: str | None, lo: str | None = None, hi: str | None = None):
    return AciPolicyFilterEntry(
        name="e", ether_type="ip", protocol=proto, destination_port_from=lo, destination_port_to=hi
    )


def _contract(name, entries, providers=(), consumers=(), scope="context", tenant="T"):
    return AciPolicyContract(
        tenant=tenant,
        name=name,
        scope=scope,
        subjects=(
            AciPolicySubject(
                name="s",
                filters=(AciPolicyFilter(name="f", tenant=tenant, entries=tuple(entries)),),
            ),
        ),
        provider_epgs=tuple(providers),
        consumer_epgs=tuple(consumers),
    )


WEB, APP, DB = _dn("AP", "web"), _dn("AP", "app"), _dn("AP", "db")
OTHER_AP_DB = _dn("AP2", "db")


def _snap(contracts=(), vrf=None, flags=(), extra_epgs=(), l3outs=()):
    epgs = {
        dn: AciPolicyEpg(
            epg_dn=dn, tenant="T", app_profile=dn.split("/")[2][3:], epg=dn.split("-")[-1]
        )
        for dn in (WEB, APP, DB, OTHER_AP_DB, *extra_epgs)
    }
    return AciPolicySnapshot(
        epgs=epgs,
        contracts={(c.tenant, c.name): c for c in contracts},
        l3outs={(o.tenant, o.name): o for o in l3outs},
        vrfs={("T", "v1"): vrf or AciVrfPolicy(tenant="T", name="v1")},
        flags={f.epg_dn: f for f in flags},
    )


def _party(address: str, epg_dn: str, vrf: str = VRF, esg: str | None = None) -> AciFlowParty:
    from services.aci.policy_search import readable_epg

    return AciFlowParty(
        address=address,
        how="endpoint",
        epg_dn=epg_dn,
        epg_path=readable_epg(epg_dn),
        vrf=vrf,
        esg=esg,
    )


SQL = _contract("sql", [_entry("tcp", "1433")], providers=[DB], consumers=[WEB])


def _flow(snap, src=WEB, dst=DB, protocol="tcp", port=1433, **kw):
    return assess_flow(snap, _party("10.0.0.1", src, **kw), _party("10.0.0.2", dst), protocol, port)


def test_a_contract_the_destination_provides_and_the_source_consumes_permits_the_port() -> None:
    out = _flow(_snap([SQL]))
    assert (out.verdict, out.reason) == ("permitted", "contract_permits")
    assert out.contracts[0].matching_entries == ("tcp 1433",)


def test_the_wrong_port_is_not_permitted_and_shows_what_the_contract_allows() -> None:
    out = _flow(_snap([SQL]), port=443)
    assert (out.verdict, out.reason) == ("not_permitted", "contract_wrong_port")
    assert out.contracts[0].entries == ("tcp 1433",) and out.contracts[0].matching_entries == ()


def test_the_wrong_protocol_is_not_permitted() -> None:
    assert _flow(_snap([SQL]), protocol="udp").reason == "contract_wrong_port"


def test_the_direction_matters_and_the_reverse_contract_is_mentioned() -> None:
    out = _flow(_snap([SQL]), src=DB, dst=WEB, port=1433)
    assert (out.verdict, out.reason) == ("not_permitted", "no_contract")
    assert any("opposite direction" in n for n in out.notes)


def test_no_contract_at_all_is_an_implicit_deny() -> None:
    out = _flow(_snap([SQL]), src=WEB, dst=APP)
    assert (out.verdict, out.reason) == ("not_permitted", "no_contract") and not out.notes


def test_a_range_and_an_entry_without_a_port_cover_the_port() -> None:
    ranged = _contract("r", [_entry("tcp", "8000", "9000")], [DB], [WEB])
    anyport = _contract("a", [_entry("tcp")], [DB], [WEB])
    assert _flow(_snap([ranged]), port=8443).verdict == "permitted"
    assert _flow(_snap([anyport]), port=22).verdict == "permitted"


def test_icmp_needs_no_port() -> None:
    ping = _contract("ping", [_entry("icmp")], [DB], [WEB])
    assert _flow(_snap([ping]), protocol="icmp", port=None).verdict == "permitted"


def test_an_unenforced_vrf_permits_everything() -> None:
    snap = _snap(vrf=AciVrfPolicy(tenant="T", name="v1", enforced=False))
    assert _flow(snap, src=WEB, dst=APP).reason == "unenforced_vrf"


def test_the_same_epg_is_permitted_unless_it_is_isolated() -> None:
    assert _flow(_snap(), src=WEB, dst=WEB).reason == "same_epg"
    isolated = _snap(flags=[AciEpgFlags(epg_dn=WEB, isolated=True)])
    out = _flow(isolated, src=WEB, dst=WEB)
    assert (out.verdict, out.reason) == ("not_permitted", "same_epg_isolated")


def test_preferred_group_needs_the_vrf_switch_and_both_members() -> None:
    vrf = AciVrfPolicy(tenant="T", name="v1", preferred_group=True)
    both = _snap(
        vrf=vrf,
        flags=[
            AciEpgFlags(epg_dn=WEB, preferred_group=True),
            AciEpgFlags(epg_dn=APP, preferred_group=True),
        ],
    )
    assert _flow(both, src=WEB, dst=APP).reason == "preferred_group"
    one = _snap(vrf=vrf, flags=[AciEpgFlags(epg_dn=WEB, preferred_group=True)])
    assert _flow(one, src=WEB, dst=APP).reason == "no_contract"
    off = _snap(
        flags=[
            AciEpgFlags(epg_dn=WEB, preferred_group=True),
            AciEpgFlags(epg_dn=APP, preferred_group=True),
        ]
    )
    assert _flow(off, src=WEB, dst=APP).reason == "no_contract"


def test_vzany_contracts_count_for_every_epg_of_the_vrf() -> None:
    any_ssh = _contract("ssh", [_entry("tcp", "22")])
    vrf = AciVrfPolicy(tenant="T", name="v1", any_provided=("T/ssh",), any_consumed=("T/ssh",))
    out = _flow(_snap([any_ssh], vrf=vrf), src=WEB, dst=APP, port=22)
    assert (out.verdict, out.reason) == ("permitted", "contract_permits")
    only_consumer = AciVrfPolicy(tenant="T", name="v1", any_consumed=("T/ssh",))
    assert _flow(_snap([any_ssh], vrf=only_consumer), src=WEB, dst=APP, port=22).verdict == (
        "not_permitted"
    )


def test_a_vzany_provider_with_an_epg_consumer_permits() -> None:
    contract = _contract("svc", [_entry("tcp", "80")], consumers=[WEB])
    vrf = AciVrfPolicy(tenant="T", name="v1", any_provided=("T/svc",))
    assert _flow(_snap([contract], vrf=vrf), src=WEB, dst=APP, port=80).verdict == "permitted"


@pytest.mark.parametrize(
    "scope,dst,expected",
    [
        ("application-profile", DB, "permitted"),
        ("application-profile", OTHER_AP_DB, "no_contract"),
        ("tenant", OTHER_AP_DB, "permitted"),
        ("context", OTHER_AP_DB, "permitted"),
        ("global", OTHER_AP_DB, "permitted"),
    ],
)
def test_the_contract_scope_must_reach_both_epgs(scope: str, dst: str, expected: str) -> None:
    contract = _contract("c", [_entry("tcp", "1433")], [dst], [WEB], scope=scope)
    out = _flow(_snap([contract]), dst=dst)
    assert out.reason in (expected, "contract_permits") and (out.verdict == "permitted") == (
        expected == "permitted"
    )


def test_a_taboo_contract_turns_a_permit_into_unknown_but_not_a_deny() -> None:
    taboo = [AciEpgFlags(epg_dn=DB, taboo=("block",))]
    out = _flow(_snap([SQL], flags=taboo))
    assert (out.verdict, out.reason) == ("unknown", "taboo_not_evaluated")
    assert _flow(_snap([SQL], flags=taboo), port=443).verdict == "not_permitted"


def test_different_vrfs_and_esg_and_unknown_sides_are_unknown() -> None:
    snap = _snap([SQL])
    other = assess_flow(
        snap, _party("10.0.0.1", WEB), _party("10.0.0.2", DB, vrf="T/v2"), "tcp", 1433
    )
    assert (other.verdict, other.reason) == ("unknown", "different_vrf")
    esg = _flow(snap, esg="T/AP/gold")
    assert (esg.verdict, esg.reason) == ("unknown", "esg_not_evaluated")
    missing = assess_flow(
        snap, AciFlowParty(address="10.9.9.9"), _party("10.0.0.2", DB), "tcp", 1433
    )
    assert (missing.verdict, missing.reason) == ("unknown", "source_not_found")
    assert "10.9.9.9" in missing.explanation


def test_an_unknown_vrf_is_a_note_not_an_answer() -> None:
    src = _party("10.0.0.1", WEB, vrf=VRF)
    dst = AciFlowParty(**{**_party("10.0.0.2", DB).model_dump(), "vrf": None})
    out = assess_flow(_snap([SQL]), src, dst, "tcp", 1433)
    assert out.verdict == "permitted" and any("VRF" in n for n in out.notes)


# -- parties ---------------------------------------------------------------------------------


def test_an_endpoint_becomes_a_party_with_its_epg_and_vrf() -> None:
    endpoint = AciEndpoint(
        mac="AA:BB:CC:00:00:01",
        tenant="T",
        app_profile="AP",
        epg="web",
        vrf="T/v1",
        ips=("10.0.0.1",),
    )
    party = party_for_endpoint("10.0.0.1", endpoint)
    assert (party.how, party.epg_dn, party.epg_path, party.vrf) == (
        "endpoint",
        WEB,
        "T/AP/web",
        "T/v1",
    )


def test_an_external_epg_endpoint_keeps_its_l3out_path() -> None:
    endpoint = AciEndpoint(mac="AA:BB:CC:00:00:01", tenant="T", external_epg="corp/default")
    party = party_for_endpoint("10.0.0.1", endpoint)
    assert party.epg_dn == "uni/tn-T/out-corp/instP-default"


L3OUT = AciPolicyL3Out(
    tenant="T",
    name="corp",
    vrf="v1",
    external_epgs=(
        AciExternalEpg(
            epg_dn="uni/tn-T/out-corp/instP-all",
            name="all",
            subnets=(AciExternalSubnet(ip="0.0.0.0/0", scope=("import-security",)),),
        ),
        AciExternalEpg(
            epg_dn="uni/tn-T/out-corp/instP-dc",
            name="dc",
            subnets=(
                AciExternalSubnet(ip="10.20.0.0/16", scope=("import-security",)),
                AciExternalSubnet(ip="10.30.0.0/16", scope=("export-rtctrl",)),
            ),
        ),
    ),
)


def test_an_unlearned_address_takes_the_longest_import_security_subnet() -> None:
    snap = _snap(l3outs=[L3OUT])
    assert external_party(snap, "10.20.1.1").epg_dn == "uni/tn-T/out-corp/instP-dc"
    assert external_party(snap, "8.8.8.8").epg_dn == "uni/tn-T/out-corp/instP-all"
    # 10.30/16 is only an export subnet: it does not classify, so the default route does.
    assert external_party(snap, "10.30.1.1").epg_dn == "uni/tn-T/out-corp/instP-all"
    assert external_party(_snap(), "8.8.8.8").how == "unknown"


def test_parties_prefers_learned_endpoints_and_caps_them() -> None:
    snap = _snap(l3outs=[L3OUT])
    endpoints = [
        AciEndpoint(mac=f"AA:BB:CC:00:00:0{i}", tenant="T", app_profile="AP", epg="web", vrf="T/v1")
        for i in range(5)
    ]
    assert len(parties(snap, "10.0.0.1", endpoints)) == 3
    assert parties(snap, "10.20.1.1", [])[0].how == "external_subnet"


def test_an_external_destination_in_the_same_vrf_is_matched_by_name() -> None:
    web = _party("10.0.0.1", WEB)
    contract = _contract("out", [_entry("tcp", "443")], ["uni/tn-T/out-corp/instP-all"], [WEB])
    snap = _snap([contract], l3outs=[L3OUT])
    out = assess_flow(snap, web, external_party(snap, "8.8.8.8"), "tcp", 443)
    assert (out.verdict, out.reason) == ("permitted", "contract_permits")


def test_describe_entry() -> None:
    assert describe_entry(_entry("tcp", "443")) == "tcp 443"
    assert describe_entry(_entry("udp", "1000", "2000")) == "udp 1000-2000"
    assert describe_entry(_entry("tcp")) == "tcp"
    assert describe_entry(_entry(None)) == "any"

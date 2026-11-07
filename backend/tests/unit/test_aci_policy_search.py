"""Pure policy searches and the snapshot cache (no I/O)."""

from __future__ import annotations

import asyncio

import pytest

from models.aci_policy import (
    AciPolicyContract,
    AciPolicyEpg,
    AciPolicyFilter,
    AciPolicyFilterEntry,
    AciPolicySubject,
)
from services.aci.policy_cache import PolicyCache
from services.aci.policy_search import (
    closest_names,
    contracts_between,
    entry_covers,
    readable_epg,
    resolve_epgs,
    search_contracts,
    search_epgs,
)
from services.aci.policy_service import AciPolicySnapshot


def _dn(tenant: str, ap: str, epg: str) -> str:
    return f"uni/tn-{tenant}/ap-{ap}/epg-{epg}"


def _epg(
    tenant: str, ap: str, name: str, provided=(), consumed=(), bd: str = "bd1", tag: str = "1"
):
    return AciPolicyEpg(
        epg_dn=_dn(tenant, ap, name),
        tenant=tenant,
        app_profile=ap,
        epg=name,
        pc_tag=tag,
        bridge_domain=bd,
        provided=tuple(provided),
        consumed=tuple(consumed),
    )


def _entry(
    proto: str | None, lo: str | None = None, hi: str | None = None, ether: str | None = "ip"
):
    return AciPolicyFilterEntry(
        name="e", ether_type=ether, protocol=proto, destination_port_from=lo, destination_port_to=hi
    )


def _contract(tenant: str, name: str, entries=(), provider=(), consumer=(), scope="context"):
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
        provider_epgs=tuple(provider),
        consumer_epgs=tuple(consumer),
    )


WEB, APP, DB = (_epg("T", "AP", n) for n in ("web", "app", "db"))
WEB = _epg("T", "AP", "web", provided=["common/web"], consumed=["common/sql"], tag="10")
DB = _epg("T", "AP", "db", provided=["common/sql"], bd="bd2", tag="30")
OTHER_DB = _epg("U", "AP2", "db")
SQL = _contract("common", "sql", [_entry("tcp", "1433")], [DB.epg_dn], [WEB.epg_dn, APP.epg_dn])
WEBC = _contract("common", "web", [_entry("tcp", "https")], [WEB.epg_dn], [])
ANY = _contract("common", "default", [_entry(None)], [], [])
SNAP = AciPolicySnapshot(
    epgs={e.epg_dn: e for e in (WEB, APP, DB, OTHER_DB)},
    contracts={(c.tenant, c.name): c for c in (SQL, WEBC, ANY)},
)


def test_readable_epg_names() -> None:
    assert readable_epg(_dn("T", "AP", "web")) == "T/AP/web"
    assert readable_epg("uni/tn-T/out-O/instP-X") == "T/O/X (external)"
    assert readable_epg("weird") == "weird"


def test_search_epgs_filters() -> None:
    assert [e.epg for e in search_epgs(SNAP, name_contains="DB")] == ["db", "db"]
    assert [e.epg for e in search_epgs(SNAP, tenant="T", bridge_domain="bd2")] == ["db"]
    assert [e.epg for e in search_epgs(SNAP, provides="sql")] == ["db"]  # bare name
    assert [e.epg for e in search_epgs(SNAP, consumes="common/sql")] == ["web"]
    assert [e.epg for e in search_epgs(SNAP, pc_tag="10")] == ["web"]
    assert search_epgs(SNAP, provides="nothing") == []


def test_resolve_epgs_exact_and_by_name() -> None:
    assert len(resolve_epgs(SNAP, "T/AP/web")) == 1
    assert len(resolve_epgs(SNAP, "db")) == 2  # ambiguous bare name
    assert resolve_epgs(SNAP, "T/AP/nope") == []


def test_closest_names() -> None:
    assert closest_names("wbe", ["web", "app", "db"]) == ["web"]
    assert closest_names("ap", ["web", "app", "db"]) == ["app"]  # substring fallback
    assert closest_names("zzzz", ["web"]) == []


@pytest.mark.parametrize(
    "entry,proto,port,expected",
    [
        (_entry("tcp", "1433"), "tcp", 1433, True),
        (_entry("tcp", "1433"), "tcp", 1434, False),
        (_entry("tcp", "1433"), "udp", 1433, False),
        (_entry("tcp", "1000", "2000"), "tcp", 1500, True),  # range
        (_entry("tcp", "https"), "tcp", 443, True),  # named port
        (_entry("tcp", "weirdname"), "tcp", 443, False),  # unknown name never matches
        (_entry("tcp"), "tcp", 22, True),  # no port in entry = any port
        (_entry(None), "udp", 53, True),  # no protocol = any
        (_entry("icmp"), "tcp", None, False),
        (_entry("tcp", "80", ether="arp"), "tcp", 80, False),  # not an IP entry
        (_entry("tcp", "1433"), "tcp", None, True),  # protocol only
    ],
)
def test_entry_covers(
    entry: AciPolicyFilterEntry, proto: str, port: int | None, expected: bool
) -> None:
    assert entry_covers(entry, proto, port) is expected


def test_search_contracts_by_port_and_relations() -> None:
    names = lambda rows: [c.name for c in rows]  # noqa: E731
    assert names(search_contracts(SNAP, protocol="tcp", port=1433)) == ["default", "sql"]
    assert names(search_contracts(SNAP, protocol="tcp", port=443)) == ["default", "web"]
    assert names(search_contracts(SNAP, provided_by=[DB.epg_dn])) == ["sql"]
    assert names(search_contracts(SNAP, consumed_by=[APP.epg_dn])) == ["sql"]
    assert names(search_contracts(SNAP, name_contains="WE")) == ["web"]
    assert names(search_contracts(SNAP, tenant="nope")) == []


def test_contracts_between_both_directions() -> None:
    a_b, b_a = contracts_between(SNAP, DB, WEB)
    assert [c.name for c in a_b] == ["sql"] and b_a == []
    a_b, b_a = contracts_between(SNAP, WEB, DB)
    assert a_b == [] and [c.name for c in b_a] == ["sql"]
    assert contracts_between(SNAP, WEB, OTHER_DB) == ([], [])


# -- cache -------------------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_cache_ttl_and_age() -> None:
    clock, calls = Clock(), []

    async def loader() -> AciPolicySnapshot:
        calls.append(1)
        return SNAP

    cache = PolicyCache(ttl=120, clock=clock)

    async def run() -> list[float]:
        ages = [(await cache.get("k", loader))[1]]
        clock.now = 100
        ages.append((await cache.get("k", loader))[1])
        clock.now = 121
        ages.append((await cache.get("k", loader))[1])
        return ages

    assert asyncio.run(run()) == [0.0, 100.0, 0.0]
    assert len(calls) == 2


def test_cache_single_flight() -> None:
    calls = []

    async def loader() -> AciPolicySnapshot:
        calls.append(1)
        await asyncio.sleep(0.05)
        return SNAP

    cache = PolicyCache()

    async def run() -> None:
        await asyncio.gather(*(cache.get("k", loader) for _ in range(5)))

    asyncio.run(run())
    assert len(calls) == 1


def test_cache_failure_is_not_cached_and_keys_are_separate() -> None:
    state = {"fail": True}

    async def loader() -> AciPolicySnapshot:
        if state["fail"]:
            raise OSError("down")
        return SNAP

    cache = PolicyCache()

    async def run() -> None:
        with pytest.raises(OSError):
            await cache.get("a", loader)
        state["fail"] = False
        await cache.get("a", loader)
        await cache.get("b", loader)

    asyncio.run(run())


def test_cache_evicts_the_oldest() -> None:
    calls: list[str] = []

    def loader_for(key: str):
        async def loader() -> AciPolicySnapshot:
            calls.append(key)
            return SNAP

        return loader

    cache = PolicyCache(max_entries=2)

    async def run() -> None:
        for key in ("a", "b", "c", "a"):
            await cache.get(key, loader_for(key))

    asyncio.run(run())
    assert calls == ["a", "b", "c", "a"]  # "a" was evicted by "c" and is loaded again


def test_cache_keeps_to_an_object_total_and_does_not_keep_one_huge_snapshot() -> None:
    from services.aci.policy_cache import weigh

    one = weigh(SNAP)
    assert one > 0
    calls: list[str] = []

    def loader_for(key: str):
        async def loader() -> AciPolicySnapshot:
            calls.append(key)
            return SNAP

        return loader

    # Room for two snapshots: the third pushes the oldest out.
    cache = PolicyCache(max_entries=10, max_objects=one * 2)

    async def run() -> None:
        for key in ("a", "b", "c", "a"):
            await cache.get(key, loader_for(key))

    asyncio.run(run())
    assert calls == ["a", "b", "c", "a"]
    # A snapshot above the cap is returned every time and never kept.
    tiny = PolicyCache(max_objects=one - 1)
    calls.clear()

    async def twice() -> None:
        await tiny.get("x", loader_for("x"))
        await tiny.get("x", loader_for("x"))

    asyncio.run(twice())
    assert calls == ["x", "x"]

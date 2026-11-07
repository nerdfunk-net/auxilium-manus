"""compare_subnets: ACI gateway subnets against Nautobot prefixes (pure, report only)."""

from __future__ import annotations

import unittest

from models.aci_subnets import AciSubnet
from services.nautobot.prefix_reader import NautobotPrefix
from workflow_steps.compare_aci_subnets.compare import compare_subnets


def _aci(
    prefix: str, *, vrf: str | None = "V1", tenant: str = "T", bd: str = "BD1", gateway=None, **kw
) -> AciSubnet:
    return AciSubnet(
        prefix=prefix,
        gateway=gateway or prefix.split("/")[0],
        tenant=tenant,
        bridge_domain=bd,
        vrf=vrf,
        **kw,
    )


def _nb(
    prefix: str, namespace: str | None = "Global", status: str = "Active", type_: str = "network"
) -> NautobotPrefix:
    return NautobotPrefix(prefix=prefix, namespace=namespace, status=status, type=type_)


def _compare(aci, nb, **kw):
    options = {"namespace": "Global", "namespace_from_vrf": False, "scope_prefixes": ()}
    options.update(kw)
    return compare_subnets(aci, nb, **options)


class MatchTests(unittest.TestCase):
    def test_an_exact_prefix_in_the_namespace_matches(self) -> None:
        report = _compare([_aci("10.1.1.0/24")], [_nb("10.1.1.0/24")])
        self.assertEqual([m["prefix"] for m in report["matched"]], ["10.1.1.0/24"])
        self.assertEqual(report["missing_in_nautobot"], [])
        self.assertEqual(report["summary"]["matched"], 1)

    def test_a_prefix_of_any_type_or_status_counts_as_present(self) -> None:
        for type_ in ("container", "pool"):
            with self.subTest(type=type_):
                report = _compare(
                    [_aci("10.1.1.0/24")], [_nb("10.1.1.0/24", type_=type_, status="Deprecated")]
                )
                self.assertEqual(report["summary"]["matched"], 1)

    def test_the_same_prefix_in_another_namespace_does_not_match(self) -> None:
        report = _compare([_aci("10.1.1.0/24")], [_nb("10.1.1.0/24", namespace="Other")])
        self.assertEqual(report["summary"]["missing_in_nautobot"], 1)

    def test_a_subnet_equal_in_two_bridge_domains_is_matched_and_reported_as_an_overlap(
        self,
    ) -> None:
        aci = [_aci("10.1.1.0/24", bd="A"), _aci("10.1.1.0/24", bd="B", tenant="U")]
        report = _compare(aci, [_nb("10.1.1.0/24")])
        self.assertEqual(len(report["matched"]), 1)
        (overlap,) = report["overlaps"]
        self.assertEqual(overlap["prefix"], "10.1.1.0/24")
        self.assertEqual(
            [(o["tenant"], o["bridge_domain"]) for o in overlap["owners"]], [("T", "A"), ("U", "B")]
        )
        self.assertEqual(report["summary"]["overlaps"], 1)

    def test_the_same_owner_twice_is_not_an_overlap(self) -> None:
        report = _compare([_aci("10.1.1.0/24"), _aci("10.1.1.0/24")], [])
        self.assertEqual(report["overlaps"], [])


class MissingInNautobotTests(unittest.TestCase):
    def test_a_missing_prefix_names_the_acis_owner_and_gateway(self) -> None:
        (item,) = _compare([_aci("10.1.1.0/24", gateway="10.1.1.1")], [])["missing_in_nautobot"]
        self.assertEqual(
            (
                item["prefix"],
                item["gateway"],
                item["namespace"],
                item["tenant"],
                item["vrf"],
                item["bridge_domain"],
            ),
            ("10.1.1.0/24", "10.1.1.1", "Global", "T", "V1", "BD1"),
        )
        self.assertIsNone(item["covered_by"])

    def test_the_smallest_covering_prefix_is_named(self) -> None:
        nb = [_nb("10.0.0.0/8"), _nb("10.1.0.0/16"), _nb("10.2.0.0/16"), _nb("192.168.0.0/16")]
        (item,) = _compare([_aci("10.1.1.0/24")], nb)["missing_in_nautobot"]
        self.assertEqual(item["covered_by"], "10.1.0.0/16")

    def test_a_covering_prefix_of_another_namespace_is_ignored(self) -> None:
        (item,) = _compare([_aci("10.1.1.0/24")], [_nb("10.1.0.0/16", namespace="Other")])[
            "missing_in_nautobot"
        ]
        self.assertIsNone(item["covered_by"])

    def test_ipv6_is_compared_too(self) -> None:
        report = _compare([_aci("2001:db8:1::/64")], [_nb("2001:db8::/32")])
        self.assertEqual(report["missing_in_nautobot"][0]["covered_by"], "2001:db8::/32")

    def test_a_sorted_report(self) -> None:
        report = _compare(
            [_aci("10.9.0.0/24"), _aci("10.1.0.0/24"), _aci("10.2.0.0/24", tenant="A")], []
        )
        self.assertEqual(
            [m["prefix"] for m in report["missing_in_nautobot"]],
            ["10.2.0.0/24", "10.1.0.0/24", "10.9.0.0/24"],
        )


class NamespaceTests(unittest.TestCase):
    def test_the_vrf_name_can_be_the_namespace(self) -> None:
        aci = [_aci("10.1.1.0/24", vrf="Red"), _aci("10.1.1.0/24", vrf="Blue", bd="BD2")]
        nb = [_nb("10.1.1.0/24", namespace="Red")]
        report = _compare(aci, nb, namespace_from_vrf=True)
        self.assertEqual([m["namespace"] for m in report["matched"]], ["Red"])
        self.assertEqual([m["namespace"] for m in report["missing_in_nautobot"]], ["Blue"])
        self.assertEqual(report["overlaps"], [])  # different VRFs are different address spaces

    def test_a_subnet_without_a_vrf_is_skipped_in_vrf_mode(self) -> None:
        report = _compare([_aci("10.1.1.0/24", vrf=None)], [], namespace_from_vrf=True)
        self.assertEqual(report["missing_in_nautobot"], [])
        self.assertEqual(
            [(s["prefix"], s["reason"]) for s in report["skipped"]], [("10.1.1.0/24", "no_vrf")]
        )
        self.assertEqual(report["summary"]["skipped"], 1)

    def test_a_subnet_without_a_vrf_is_fine_with_a_fixed_namespace(self) -> None:
        report = _compare([_aci("10.1.1.0/24", vrf=None)], [])
        self.assertEqual(report["summary"]["missing_in_nautobot"], 1)
        self.assertEqual(report["skipped"], [])


class MissingInAciTests(unittest.TestCase):
    def test_not_computed_without_a_scope(self) -> None:
        report = _compare([], [_nb("10.1.1.0/24")])
        self.assertIsNone(report["missing_in_aci"])
        self.assertIsNone(report["summary"]["missing_in_aci"])

    def test_a_nautobot_network_inside_the_scope_that_aci_lacks(self) -> None:
        nb = [_nb("10.1.1.0/24"), _nb("10.1.2.0/24", status="Reserved"), _nb("172.16.0.0/24")]
        report = _compare([_aci("10.1.1.0/24")], nb, scope_prefixes=("10.1.0.0/16",))
        self.assertEqual(
            [(m["prefix"], m["status"]) for m in report["missing_in_aci"]],
            [("10.1.2.0/24", "Reserved")],
        )

    def test_containers_pools_and_the_scope_itself_are_not_candidates(self) -> None:
        nb = [
            _nb("10.1.0.0/16"),
            _nb("10.1.4.0/22", type_="container"),
            _nb("10.1.5.0/24", type_="pool"),
        ]
        report = _compare([], nb, scope_prefixes=("10.1.0.0/16",))
        self.assertEqual(report["missing_in_aci"], [])

    def test_a_fixed_namespace_only_looks_at_that_namespace(self) -> None:
        nb = [_nb("10.1.2.0/24", namespace="Other")]
        self.assertEqual(_compare([], nb, scope_prefixes=("10.1.0.0/16",))["missing_in_aci"], [])
        self.assertEqual(
            len(
                _compare([], nb, scope_prefixes=("10.1.0.0/16",), namespace_from_vrf=True)[
                    "missing_in_aci"
                ]
            ),
            1,
        )

    def test_a_prefix_matching_in_the_acis_namespace_is_not_reported(self) -> None:
        aci = [_aci("10.1.1.0/24", vrf="Red")]
        nb = [_nb("10.1.1.0/24", namespace="Red")]
        report = _compare(aci, nb, namespace_from_vrf=True, scope_prefixes=("10.1.0.0/16",))
        self.assertEqual(report["missing_in_aci"], [])

    def test_a_scope_must_be_a_prefix(self) -> None:
        with self.assertRaises(ValueError):
            _compare([], [], scope_prefixes=("not a prefix",))

    def test_a_scope_in_host_form_is_normalised(self) -> None:
        nb = [_nb("10.1.2.0/24")]
        self.assertEqual(
            len(_compare([], nb, scope_prefixes=("10.1.5.0/16",))["missing_in_aci"]), 1
        )


class SummaryTests(unittest.TestCase):
    def test_counts_and_the_drift_flag(self) -> None:
        report = _compare([_aci("10.1.1.0/24"), _aci("10.1.2.0/24")], [_nb("10.1.1.0/24")])
        self.assertEqual(
            (
                report["summary"]["aci_subnets"],
                report["summary"]["matched"],
                report["summary"]["missing_in_nautobot"],
            ),
            (2, 1, 1),
        )
        self.assertTrue(report["summary"]["differences"])
        self.assertFalse(
            _compare([_aci("10.1.1.0/24")], [_nb("10.1.1.0/24")])["summary"]["differences"]
        )

    def test_overlaps_and_missing_in_aci_count_as_differences(self) -> None:
        self.assertTrue(
            _compare(
                [_aci("10.1.1.0/24", bd="A"), _aci("10.1.1.0/24", bd="B")], [_nb("10.1.1.0/24")]
            )["summary"]["differences"]
        )
        self.assertTrue(
            _compare([], [_nb("10.1.1.0/24")], scope_prefixes=("10.0.0.0/8",))["summary"][
                "differences"
            ]
        )

    def test_the_inputs_are_not_modified(self) -> None:
        aci, nb = [_aci("10.1.1.0/24")], [_nb("10.1.1.0/24")]
        _compare(aci, nb)
        self.assertEqual((aci, nb), ([_aci("10.1.1.0/24")], [_nb("10.1.1.0/24")]))


class CoverIndexTests(unittest.TestCase):
    """The covering lookup must not depend on the number of Nautobot prefixes (review finding 8)."""

    def test_it_agrees_with_the_straightforward_scan(self) -> None:
        import ipaddress
        import random

        from workflow_steps.compare_aci_subnets.compare import _CoverIndex

        rng = random.Random(7)
        prefixes = [
            f"{rng.randrange(0, 256)}.{rng.randrange(0, 256)}.0.0/{rng.choice((8, 12, 16, 20))}"
            for _ in range(200)
        ] + ["2001:db8::/32", "2001:db8:1::/48"]
        nb = [_nb(p) for p in prefixes] + [_nb("10.0.0.0/8", namespace="Other")]
        index = _CoverIndex(nb)
        for _ in range(300):
            target = ipaddress.ip_network(
                f"{rng.randrange(0, 256)}.{rng.randrange(0, 256)}.{rng.randrange(0, 256)}.0/24"
            )
            best = None
            for p in prefixes:
                network = ipaddress.ip_network(p, strict=False)
                if network.version == 4 and target.subnet_of(network):
                    if best is None or network.prefixlen > best.prefixlen:
                        best = network
            self.assertEqual(index.covering(str(target), "Global"), str(best) if best else None)
        self.assertEqual(index.covering("2001:db8:1:2::/64", "Global"), "2001:db8:1::/48")
        self.assertIsNone(index.covering("10.1.1.0/24", "Nowhere"))

    def test_an_unparseable_prefix_is_ignored_and_the_scan_is_bounded(self) -> None:
        from workflow_steps.compare_aci_subnets.compare import _CoverIndex

        index = _CoverIndex([_nb("not-a-prefix"), _nb("10.0.0.0/8")])
        self.assertEqual(index.covering("10.9.9.0/24", "Global"), "10.0.0.0/8")

    def test_a_large_fabric_with_nothing_matching_is_fast(self) -> None:
        import time

        nb = [_nb(f"10.{i // 256}.{i % 256}.0/24") for i in range(50_000)]
        aci = [_aci(f"172.16.{i % 256}.0/24") for i in range(2_000)]
        start = time.perf_counter()
        report = _compare(aci, nb)
        self.assertLess(time.perf_counter() - start, 5.0)
        self.assertGreaterEqual(report["summary"]["missing_in_nautobot"], 256)

"""Tests for services/git/device_mapping.py."""

from __future__ import annotations

import copy
import unittest

from services.git.device_mapping import (
    CORE_TARGETS,
    DEFAULT_DEVICE_MAPPING,
    IGNORE_TARGET,
    NAUTOBOT_TARGETS,
    PRIMARY_FLAG_TARGET,
    MappingRule,
    apply_device_mapping,
    apply_interface_mapping,
    collect_available_keys,
    read_primary_flag,
    resolve_primary_ip,
    resolve_source_value,
    validate_device_mapping,
    with_implicit_custom_field_rules,
)


class ValidateDeviceMappingTests(unittest.TestCase):
    def test_empty_uses_default(self) -> None:
        for raw in (None, [], {}):
            self.assertEqual(validate_device_mapping(raw), list(DEFAULT_DEVICE_MAPPING))

    def test_valid_custom_mapping(self) -> None:
        rules = validate_device_mapping(
            [
                {"source": "device_name", "target": "name"},
                {"source": "site", "target": "location.name"},
            ]
        )
        self.assertEqual(
            rules,
            [MappingRule("device_name", "name"), MappingRule("site", "location.name")],
        )

    def test_strips_whitespace(self) -> None:
        rules = validate_device_mapping([{"source": " dn ", "target": " name "}])
        self.assertEqual(rules, [MappingRule("dn", "name")])

    def test_unknown_target_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown target"):
            validate_device_mapping(
                [{"source": "a", "target": "name"}, {"source": "b", "target": "bogus.attr"}]
            )

    def test_uuid_targets_not_mappable(self) -> None:
        with self.assertRaises(ValueError):
            validate_device_mapping(
                [{"source": "a", "target": "name"}, {"source": "b", "target": "id"}]
            )

    def test_duplicate_target_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_device_mapping(
                [{"source": "a", "target": "name"}, {"source": "b", "target": "name"}]
            )

    def test_empty_source_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "source"):
            validate_device_mapping([{"source": " ", "target": "name"}])

    def test_missing_name_target_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "name"):
            validate_device_mapping([{"source": "site", "target": "location.name"}])

    def test_non_list_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_device_mapping("name")

    def test_non_dict_row_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_device_mapping(["name"])


class CustomFieldAndInterfaceTargetTests(unittest.TestCase):
    NAME = {"source": "name", "target": "name"}

    def test_custom_field_target_accepted(self) -> None:
        rules = validate_device_mapping(
            [self.NAME, {"source": "x", "target": "custom_fields.snmp_credentials"}]
        )
        self.assertEqual(rules[1].target, "custom_fields.snmp_credentials")

    def test_invalid_custom_field_names_rejected(self) -> None:
        bad_names = (
            "custom_fields.",
            "custom_fields.a b",
            "custom_fields.a.b",
            "custom_fields.a-b",
        )
        for bad in bad_names:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_device_mapping([self.NAME, {"source": "x", "target": bad}])

    def test_interface_targets_accepted(self) -> None:
        rules = validate_device_mapping(
            [
                self.NAME,
                {"source": "i", "target": "interfaces.name"},
                {"source": "ip", "target": "interfaces.ip_addresses.address"},
            ]
        )
        self.assertEqual(len(rules), 3)

    def test_interface_targets_without_interface_name_rejected(self) -> None:
        for target in ("interfaces.ip_addresses.address", "interfaces.description"):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "interfaces.name"):
                validate_device_mapping([self.NAME, {"source": "ip", "target": target}])

    def test_interface_name_alone_is_valid(self) -> None:
        rules = validate_device_mapping([self.NAME, {"source": "i", "target": "interfaces.name"}])
        self.assertEqual(len(rules), 2)

    def test_ignored_column_does_not_count_as_interface_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "interfaces.name"):
            validate_device_mapping(
                [
                    self.NAME,
                    {"source": "i", "target": IGNORE_TARGET},
                    {"source": "ip", "target": "interfaces.mtu"},
                ]
            )

    def test_device_mapping_ignores_interface_targets(self) -> None:
        out = apply_device_mapping(
            {"n": "r1", "i": "Eth0"},
            [MappingRule("n", "name"), MappingRule("i", "interfaces.name")],
        )
        self.assertEqual(out, {"name": "r1"})

    def test_custom_field_value_nested(self) -> None:
        out = apply_device_mapping(
            {"n": "r1", "c": "v"},
            [MappingRule("n", "name"), MappingRule("c", "custom_fields.snmp")],
        )
        self.assertEqual(out, {"name": "r1", "custom_fields": {"snmp": "v"}})

    def test_apply_interface_mapping(self) -> None:
        rules = [
            MappingRule("i", "interfaces.name"),
            MappingRule("ip", "interfaces.ip_addresses.address"),
            MappingRule("st", "interfaces.status.name"),
            MappingRule("n", "name"),
        ]
        entry = {"i": "Eth0", "ip": "1.1.1.1/24", "st": "Active", "n": "r"}
        out = apply_interface_mapping(entry, rules)
        self.assertEqual(
            out,
            {
                "name": "Eth0",
                "status": {"name": "Active"},
                "ip_addresses": [{"address": "1.1.1.1/24"}],
            },
        )

    def test_apply_interface_mapping_requires_name(self) -> None:
        rules = [MappingRule("ip", "interfaces.ip_addresses.address")]
        self.assertIsNone(apply_interface_mapping({"ip": "1.1.1.1/24"}, rules))
        self.assertIsNone(apply_interface_mapping({}, [MappingRule("i", "interfaces.name")]))


class ImplicitCustomFieldRuleTests(unittest.TestCase):
    def test_cf_keys_get_rules(self) -> None:
        rules = with_implicit_custom_field_rules(
            [MappingRule("name", "name")], ["name", "cf_snmp_credentials", "cf_net", "other"]
        )
        self.assertEqual(
            rules[1:],
            [
                MappingRule("cf_snmp_credentials", "custom_fields.snmp_credentials"),
                MappingRule("cf_net", "custom_fields.net"),
            ],
        )

    def test_explicit_source_not_duplicated(self) -> None:
        base = [MappingRule("name", "name"), MappingRule("cf_net", "custom_fields.network")]
        self.assertEqual(with_implicit_custom_field_rules(base, ["cf_net"]), base)

    def test_explicit_target_not_duplicated(self) -> None:
        base = [MappingRule("name", "name"), MappingRule("net", "custom_fields.net")]
        self.assertEqual(with_implicit_custom_field_rules(base, ["cf_net"]), base)

    def test_bare_or_invalid_cf_keys_skipped(self) -> None:
        base = [MappingRule("name", "name")]
        self.assertEqual(with_implicit_custom_field_rules(base, ["cf_", "cf_a b", "cf_a.b"]), base)


class IgnoreTargetTests(unittest.TestCase):
    NAME = {"source": "name", "target": "name"}

    def test_ignore_target_accepted_and_may_repeat(self) -> None:
        rules = validate_device_mapping(
            [
                self.NAME,
                {"source": "a", "target": IGNORE_TARGET},
                {"source": "b", "target": IGNORE_TARGET},
            ]
        )
        self.assertEqual([r.target for r in rules], ["name", IGNORE_TARGET, IGNORE_TARGET])

    def test_ignored_columns_do_not_reach_the_device(self) -> None:
        rules = [MappingRule("n", "name"), MappingRule("junk", IGNORE_TARGET)]
        self.assertEqual(apply_device_mapping({"n": "r1", "junk": "x"}, rules), {"name": "r1"})
        self.assertIsNone(apply_interface_mapping({"n": "r1", "junk": "x"}, rules))

    def test_ignored_cf_column_is_not_mapped_implicitly(self) -> None:
        base = [MappingRule("name", "name"), MappingRule("cf_net", IGNORE_TARGET)]
        self.assertEqual(with_implicit_custom_field_rules(base, ["cf_net"]), base)

    def test_ignore_only_mapping_still_needs_a_name(self) -> None:
        with self.assertRaises(ValueError):
            validate_device_mapping([{"source": "a", "target": IGNORE_TARGET}])


class ResolveSourceValueTests(unittest.TestCase):
    def test_flat_key(self) -> None:
        self.assertEqual(resolve_source_value({"a": 1}, "a"), 1)

    def test_dot_path(self) -> None:
        self.assertEqual(resolve_source_value({"loc": {"site": "X"}}, "loc.site"), "X")

    def test_flat_key_containing_dot_wins(self) -> None:
        self.assertEqual(resolve_source_value({"a.b": 1, "a": {"b": 2}}, "a.b"), 1)

    def test_missing_returns_none(self) -> None:
        self.assertIsNone(resolve_source_value({"a": {}}, "a.b.c"))
        self.assertIsNone(resolve_source_value({"a": "str"}, "a.b"))


class ApplyDeviceMappingTests(unittest.TestCase):
    def test_default_mapping_matches_legacy_shape(self) -> None:
        out = apply_device_mapping(
            {"name": "r1", "primary_ip4": "10.0.0.1/24", "network_driver": "ios"},
            list(DEFAULT_DEVICE_MAPPING),
        )
        self.assertEqual(
            out,
            {
                "name": "r1",
                "primary_ip4": {"address": "10.0.0.1/24"},
                "platform": {"network_driver": "ios"},
            },
        )

    def test_custom_mapping_builds_nested_shape(self) -> None:
        rules = [
            MappingRule("device_name", "name"),
            MappingRule("site", "location.name"),
            MappingRule("parent_site", "location.parent.name"),
            MappingRule("state", "status.name"),
            MappingRule("pos", "position"),
        ]
        out = apply_device_mapping(
            {
                "device_name": "r1",
                "site": "City A",
                "parent_site": "State A",
                "state": "Active",
                "pos": 3,
            },
            rules,
        )
        self.assertEqual(out["name"], "r1")
        self.assertEqual(out["location"], {"name": "City A", "parent": {"name": "State A"}})
        self.assertEqual(out["status"], {"name": "Active"})
        self.assertEqual(out["position"], "3")

    def test_dot_path_source(self) -> None:
        out = apply_device_mapping({"meta": {"n": "r1"}}, [MappingRule("meta.n", "name")])
        self.assertEqual(out, {"name": "r1"})

    def test_missing_name_returns_none(self) -> None:
        self.assertIsNone(apply_device_mapping({"site": "X"}, [MappingRule("n", "name")]))

    def test_non_dict_entry_returns_none(self) -> None:
        self.assertIsNone(apply_device_mapping("nope", list(DEFAULT_DEVICE_MAPPING)))

    def test_empty_and_none_values_skipped(self) -> None:
        out = apply_device_mapping(
            {"n": "r1", "s": "", "x": None},
            [MappingRule("n", "name"), MappingRule("s", "serial"), MappingRule("x", "role.name")],
        )
        self.assertEqual(out, {"name": "r1"})

    def test_structured_values_skipped(self) -> None:
        out = apply_device_mapping(
            {"n": "r1", "s": ["a"]}, [MappingRule("n", "name"), MappingRule("s", "serial")]
        )
        self.assertEqual(out, {"name": "r1"})

    def test_input_not_mutated(self) -> None:
        entry = {"n": "r1", "loc": {"site": "X"}}
        snapshot = copy.deepcopy(entry)
        apply_device_mapping(
            entry, [MappingRule("n", "name"), MappingRule("loc.site", "location.name")]
        )
        self.assertEqual(entry, snapshot)


class CollectAvailableKeysTests(unittest.TestCase):
    def test_top_level_and_dotted_leaf_keys(self) -> None:
        keys = collect_available_keys(
            [{"name": "a", "loc": {"site": "x", "deep": {"k": 1}}}, {"name": "b", "extra": 1}]
        )
        self.assertEqual(keys, ["extra", "loc", "loc.deep", "loc.deep.k", "loc.site", "name"])

    def test_empty(self) -> None:
        self.assertEqual(collect_available_keys([]), [])


class NamespaceAndCustomTargetTests(unittest.TestCase):
    NAME = {"source": "name", "target": "name"}
    IFACE = {"source": "interface", "target": "interfaces.name"}
    IFACE_IP = {"source": "primary_ip4", "target": "interfaces.ip_addresses.address"}
    IFACE_NS = {"source": "namespace", "target": "interfaces.ip_addresses.parent.namespace.name"}

    def test_namespace_targets_in_catalog(self) -> None:
        self.assertIn("primary_ip4.parent.namespace.name", NAUTOBOT_TARGETS)
        self.assertIn("interfaces.ip_addresses.parent.namespace.name", NAUTOBOT_TARGETS)

    def test_custom_target_accepted(self) -> None:
        rules = validate_device_mapping(
            [self.NAME, {"source": "namespace", "target": "custom.namespace"}]
        )
        self.assertEqual(rules[1], MappingRule("namespace", "custom.namespace"))

    def test_custom_target_invalid_names_rejected(self) -> None:
        for target in ("custom.", "custom.a b", "custom.a.b"):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "unknown target"):
                validate_device_mapping([self.NAME, {"source": "x", "target": target}])

    def test_duplicate_custom_target_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_device_mapping(
                [
                    self.NAME,
                    {"source": "a", "target": "custom.ns"},
                    {"source": "b", "target": "custom.ns"},
                ]
            )

    def test_interface_namespace_requires_interface_ip(self) -> None:
        with self.assertRaisesRegex(ValueError, "interfaces.ip_addresses.address"):
            validate_device_mapping([self.NAME, self.IFACE, self.IFACE_NS])

    def test_interface_namespace_with_ip_accepted(self) -> None:
        rules = validate_device_mapping([self.NAME, self.IFACE, self.IFACE_IP, self.IFACE_NS])
        self.assertEqual(len(rules), 4)

    def test_primary_ip_namespace_nests_beside_address(self) -> None:
        rules = [
            MappingRule("name", "name"),
            MappingRule("primary_ip4", "primary_ip4.address"),
            MappingRule("namespace", "primary_ip4.parent.namespace.name"),
        ]
        mapped = apply_device_mapping(
            {"name": "d1", "primary_ip4": "10.0.0.1/24", "namespace": "black"}, rules
        )
        self.assertEqual(
            mapped,
            {
                "name": "d1",
                "primary_ip4": {
                    "address": "10.0.0.1/24",
                    "parent": {"namespace": {"name": "black"}},
                },
            },
        )

    def test_custom_value_nests_under_custom(self) -> None:
        rules = [MappingRule("name", "name"), MappingRule("namespace", "custom.namespace")]
        mapped = apply_device_mapping({"name": "d1", "namespace": "black"}, rules)
        self.assertEqual(mapped, {"name": "d1", "custom": {"namespace": "black"}})

    def test_primary_ip_namespace_requires_primary_ip_address(self) -> None:
        with self.assertRaisesRegex(ValueError, "primary_ip4.address"):
            validate_device_mapping(
                [self.NAME, {"source": "ns", "target": "primary_ip4.parent.namespace.name"}]
            )

    def test_primary_ip_namespace_with_address_accepted(self) -> None:
        rules = validate_device_mapping(
            [
                self.NAME,
                {"source": "ip", "target": "primary_ip4.address"},
                {"source": "ns", "target": "primary_ip4.parent.namespace.name"},
            ]
        )
        self.assertEqual(len(rules), 3)

    def test_primary_ip_namespace_without_address_value_is_dropped(self) -> None:
        rules = [
            MappingRule("name", "name"),
            MappingRule("ip", "primary_ip4.address"),
            MappingRule("ns", "primary_ip4.parent.namespace.name"),
        ]
        mapped = apply_device_mapping(
            {"name": "d1", "ip": "", "namespace": "x", "ns": "black"}, rules
        )
        self.assertEqual(mapped, {"name": "d1"})

    def test_interface_ip_carries_namespace(self) -> None:
        rules = [
            MappingRule("interface", "interfaces.name"),
            MappingRule("primary_ip4", "interfaces.ip_addresses.address"),
            MappingRule("namespace", "interfaces.ip_addresses.parent.namespace.name"),
        ]
        iface = apply_interface_mapping(
            {"interface": "eth0", "primary_ip4": "10.0.0.1/24", "namespace": "black"}, rules
        )
        self.assertEqual(
            iface,
            {
                "name": "eth0",
                "ip_addresses": [
                    {
                        "address": "10.0.0.1/24",
                        "parent": {"namespace": {"name": "black"}},
                    }
                ],
            },
        )

    def test_interface_namespace_without_address_value_is_dropped(self) -> None:
        rules = [
            MappingRule("interface", "interfaces.name"),
            MappingRule("primary_ip4", "interfaces.ip_addresses.address"),
            MappingRule("namespace", "interfaces.ip_addresses.parent.namespace.name"),
        ]
        iface = apply_interface_mapping(
            {"interface": "eth0", "primary_ip4": "", "namespace": "black"}, rules
        )
        self.assertEqual(iface, {"name": "eth0"})


class PrimaryFlagTests(unittest.TestCase):
    BASE = [
        {"source": "name", "target": "name"},
        {"source": "interface_name", "target": "interfaces.name"},
        {"source": "interface_address", "target": "interfaces.ip_addresses.address"},
    ]

    def _validate(self, *extra: dict) -> list[MappingRule]:
        return validate_device_mapping([*self.BASE, *extra])

    def test_target_accepted_and_not_a_nautobot_target(self) -> None:
        rules = self._validate({"source": "is_primary", "target": PRIMARY_FLAG_TARGET})
        self.assertIn(PRIMARY_FLAG_TARGET, [r.target for r in rules])
        self.assertNotIn(PRIMARY_FLAG_TARGET, NAUTOBOT_TARGETS)

    def test_only_once(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self._validate(
                {"source": "a", "target": PRIMARY_FLAG_TARGET},
                {"source": "b", "target": PRIMARY_FLAG_TARGET},
            )

    def test_requires_interface_ip(self) -> None:
        with self.assertRaisesRegex(ValueError, "interfaces.ip_addresses.address"):
            validate_device_mapping(
                [
                    {"source": "name", "target": "name"},
                    {"source": "is_primary", "target": PRIMARY_FLAG_TARGET},
                ]
            )

    def test_rejected_with_explicit_primary_address(self) -> None:
        with self.assertRaisesRegex(ValueError, "primary_ip4.address"):
            self._validate(
                {"source": "is_primary", "target": PRIMARY_FLAG_TARGET},
                {"source": "mgmt", "target": "primary_ip4.address"},
            )

    def test_flag_column_does_not_reach_device_or_interface(self) -> None:
        rules = [MappingRule(**{"source": r["source"], "target": r["target"]}) for r in self.BASE]
        rules.append(MappingRule("is_primary", PRIMARY_FLAG_TARGET))
        row = {
            "name": "d",
            "interface_name": "eth0",
            "interface_address": "10.0.0.2/24",
            "is_primary": "true",
        }
        self.assertEqual(apply_device_mapping(row, rules), {"name": "d"})
        self.assertEqual(
            apply_interface_mapping(row, rules),
            {"name": "eth0", "ip_addresses": [{"address": "10.0.0.2/24"}]},
        )

    def test_read_primary_flag_values(self) -> None:
        rules = [MappingRule("p", PRIMARY_FLAG_TARGET)]
        for text in ("true", "TRUE", " yes ", "y", "1", "t"):
            self.assertIs(read_primary_flag({"p": text}, rules), True, text)
        for text in ("false", "No", "n", "0", "f", "", "  "):
            self.assertIs(read_primary_flag({"p": text}, rules), False, text)
        self.assertIs(read_primary_flag({}, rules), False)
        self.assertIsNone(read_primary_flag({"p": "maybe"}, rules))

    def test_read_primary_flag_without_rule_is_false(self) -> None:
        self.assertIs(read_primary_flag({"p": "true"}, [MappingRule("n", "name")]), False)

    def test_resolve_none(self) -> None:
        res = resolve_primary_ip([])
        self.assertIsNone(res.primary_ip4)
        self.assertEqual(res.problems, ())

    def test_resolve_one_carries_namespace(self) -> None:
        iface = {
            "name": "eth0",
            "ip_addresses": [
                {"address": "10.0.0.2/24", "parent": {"namespace": {"name": "black"}}}
            ],
        }
        res = resolve_primary_ip([iface])
        self.assertEqual(
            res.primary_ip4,
            {"address": "10.0.0.2/24", "parent": {"namespace": {"name": "black"}}},
        )
        self.assertEqual(res.problems, ())

    def test_resolve_multiple_is_a_problem(self) -> None:
        a = {"name": "eth0", "ip_addresses": [{"address": "10.0.0.2/24"}]}
        b = {"name": "eth1", "ip_addresses": [{"address": "192.168.1.1/24"}]}
        res = resolve_primary_ip([a, b])
        self.assertIsNone(res.primary_ip4)
        self.assertEqual([p.code for p in res.problems], ["multiple_primary_ip"])
        self.assertIn("eth0 (10.0.0.2/24)", res.problems[0].message)
        self.assertIn("eth1 (192.168.1.1/24)", res.problems[0].message)

    def test_resolve_identical_duplicates_collapse(self) -> None:
        a = {"name": "eth0", "ip_addresses": [{"address": "10.0.0.2/24"}]}
        res = resolve_primary_ip([a, dict(a)])
        self.assertEqual(res.primary_ip4, {"address": "10.0.0.2/24"})
        self.assertEqual(res.problems, ())

    def test_resolve_flag_without_ip_is_a_problem(self) -> None:
        res = resolve_primary_ip([{"name": "eth0"}])
        self.assertIsNone(res.primary_ip4)
        self.assertEqual([p.code for p in res.problems], ["primary_without_address"])

    def test_resolve_same_address_in_two_namespaces_is_multiple(self) -> None:
        def iface(namespace: str) -> dict:
            return {
                "name": "eth0",
                "ip_addresses": [
                    {"address": "10.0.0.2/24", "parent": {"namespace": {"name": namespace}}}
                ],
            }

        res = resolve_primary_ip([iface("Global"), iface("black")])
        self.assertIsNone(res.primary_ip4)
        self.assertEqual([p.code for p in res.problems], ["multiple_primary_ip"])
        self.assertIn("black", res.problems[0].message)

    def test_problem_text_is_single_line_and_capped(self) -> None:
        nasty = {"name": "eth0\nINFO forged", "ip_addresses": [{"address": "10.0.0.1/24"}]}
        other = {"name": "x" * 500, "ip_addresses": [{"address": "10.0.0.2/24"}]}
        message = resolve_primary_ip([nasty, other]).problems[0].message
        self.assertNotIn("\n", message)
        self.assertLess(len(message), 400)

    def test_problem_list_is_capped(self) -> None:
        many = [
            {"name": f"e{i}", "ip_addresses": [{"address": f"10.0.0.{i}/24"}]} for i in range(20)
        ]
        message = resolve_primary_ip(many).problems[0].message
        self.assertIn("20 interfaces", message)
        self.assertIn("more", message)
        self.assertNotIn("e19", message)


class CatalogTests(unittest.TestCase):
    def test_core_targets_subset_of_catalog(self) -> None:
        self.assertLessEqual(set(CORE_TARGETS), set(NAUTOBOT_TARGETS))

    def test_no_uuid_targets(self) -> None:
        self.assertFalse([t for t in NAUTOBOT_TARGETS if t == "id" or t.endswith(".id")])

    def test_default_mapping_targets_in_catalog(self) -> None:
        self.assertLessEqual({r.target for r in DEFAULT_DEVICE_MAPPING}, set(NAUTOBOT_TARGETS))


if __name__ == "__main__":
    unittest.main()

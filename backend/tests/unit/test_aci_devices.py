"""Tests for ACI device filters, normalization and the device service.

Fixtures are trimmed copies of what the DevNet always-on APIC (6.1(4h)) returned on 2026-11-06.
"""

from __future__ import annotations

import unittest
from typing import Any

from models.aci import AciDevice
from services.aci.common.exceptions import AciAPIError, AciTooManyDevicesError, AciValidationError
from services.aci.credentials import AciCredentials
from services.aci.device_filters import AciDeviceFilters, _wildcard_match
from services.aci.device_service import AciDeviceService, normalize_device

CREDS = AciCredentials(base_url="https://10.10.20.14", username="admin", password="pw")

ROLE_FILTER_FABRIC = 'or(eq(fabricNode.role,"leaf"),eq(fabricNode.role,"spine"))'
ROLE_FILTER_SYSTEM = 'or(eq(topSystem.role,"leaf"),eq(topSystem.role,"spine"))'


def _fabric_node(node_id: str, name: str, role: str, **extra: str) -> dict[str, Any]:
    pod = extra.pop("pod", "1")
    return {
        "id": node_id,
        "name": name,
        "role": role,
        "dn": f"topology/pod-{pod}/node-{node_id}",
        "model": extra.pop("model", "N9K-C9396PX"),
        "serial": extra.pop("serial", f"TEP-1-{node_id}"),
        "version": extra.pop("version", "simsw-6.1(4h)"),
        "fabricSt": extra.pop("fabricSt", "active"),
        "address": extra.pop("address", f"10.0.64.{node_id[-2:]}"),
        **extra,
    }


def _top_system(node_id: str, **extra: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "oobMgmtAddr": extra.pop("oob", "0.0.0.0"),
        "inbMgmtAddr": extra.pop("inb", "0.0.0.0"),
        "state": extra.pop("state", "in-service"),
        **extra,
    }


SANDBOX_NODES = [
    _fabric_node("101", "leaf-1", "leaf"),
    _fabric_node("102", "leaf-2", "leaf"),
    _fabric_node("201", "spine-1", "spine", model="N9K-C9508"),
]
SANDBOX_SYSTEMS = [_top_system("101"), _top_system("102"), _top_system("201")]


class _FakeClient:
    def __init__(self, nodes=None, systems=None) -> None:
        self.nodes = SANDBOX_NODES if nodes is None else nodes
        self.systems = SANDBOX_SYSTEMS if systems is None else systems
        self.calls: list[tuple[str, str | None]] = []

    async def query_class(self, credentials, class_name, *, query_filter=None, **_kw):
        self.calls.append((class_name, query_filter))
        return list(self.nodes if class_name == "fabricNode" else self.systems)


class NormalizeDeviceTests(unittest.TestCase):
    def test_sandbox_leaf_without_management_ip(self) -> None:
        device = normalize_device(_fabric_node("101", "leaf-1", "leaf"), _top_system("101"))
        assert device is not None
        self.assertEqual(device.node_id, 101)
        self.assertEqual(device.pod_id, 1)
        self.assertEqual(device.name, "leaf-1")
        self.assertEqual(device.role, "leaf")
        self.assertEqual(device.model, "N9K-C9396PX")
        self.assertEqual(device.serial_number, "TEP-1-101")
        self.assertEqual(device.software_version, "simsw-6.1(4h)")
        self.assertEqual(device.fabric_state, "active")
        self.assertEqual(device.tep_address, "10.0.64.01")
        self.assertIsNone(device.management_ip)  # 0.0.0.0 means "not set", not an address
        self.assertIsNone(device.oob_ip)
        self.assertIsNone(device.inb_ip)

    def test_oob_is_preferred_over_inband(self) -> None:
        device = normalize_device(
            _fabric_node("101", "leaf-1", "leaf"),
            _top_system("101", oob="10.1.1.5", inb="192.168.11.5"),
        )
        assert device is not None
        self.assertEqual(device.management_ip, "10.1.1.5")
        self.assertEqual(device.oob_ip, "10.1.1.5")
        self.assertEqual(device.inb_ip, "192.168.11.5")

    def test_inband_is_used_when_oob_is_unset(self) -> None:
        device = normalize_device(
            _fabric_node("101", "leaf-1", "leaf"), _top_system("101", inb="192.168.11.5")
        )
        assert device is not None
        self.assertEqual(device.management_ip, "192.168.11.5")

    def test_garbage_addresses_are_ignored(self) -> None:
        device = normalize_device(
            _fabric_node("101", "leaf-1", "leaf"),
            _top_system("101", oob="not-an-ip", inb="::"),
        )
        assert device is not None
        self.assertIsNone(device.management_ip)

    def test_missing_top_system_keeps_the_device(self) -> None:
        device = normalize_device(_fabric_node("101", "leaf-1", "leaf"), None)
        assert device is not None
        self.assertIsNone(device.management_ip)
        self.assertIsNone(device.system_state)

    def test_system_state_comes_from_top_system(self) -> None:
        device = normalize_device(
            _fabric_node("101", "leaf-1", "leaf"), _top_system("101", state="out-of-service")
        )
        assert device is not None
        self.assertEqual(device.system_state, "out-of-service")

    def test_pod_is_read_from_the_dn(self) -> None:
        device = normalize_device(_fabric_node("1101", "leaf-9", "leaf", pod="2"), None)
        assert device is not None
        self.assertEqual(device.pod_id, 2)

    def test_unparsable_dn_gives_no_pod(self) -> None:
        node = _fabric_node("101", "leaf-1", "leaf")
        node["dn"] = "weird"
        device = normalize_device(node, None)
        assert device is not None
        self.assertIsNone(device.pod_id)

    def test_controller_and_unknown_roles_are_dropped(self) -> None:
        self.assertIsNone(normalize_device(_fabric_node("1", "apic1", "controller"), None))
        self.assertIsNone(normalize_device(_fabric_node("5", "x", "unspecified"), None))

    def test_row_without_a_numeric_node_id_is_dropped(self) -> None:
        self.assertIsNone(normalize_device(_fabric_node("abc", "x", "leaf"), None))
        self.assertIsNone(normalize_device({"role": "leaf", "name": "x"}, None))

    def test_row_without_a_name_falls_back_to_the_node_id(self) -> None:
        node = _fabric_node("101", "", "leaf")
        device = normalize_device(node, None)
        assert device is not None
        self.assertEqual(device.name, "node-101")

    def test_device_is_immutable_and_keeps_raw(self) -> None:
        device = normalize_device(_fabric_node("101", "leaf-1", "leaf"), _top_system("101"))
        assert device is not None
        with self.assertRaises(Exception):  # noqa: B017 - pydantic ValidationError
            device.name = "x"  # type: ignore[misc]
        self.assertEqual(device.raw["fabric_node"]["id"], "101")
        self.assertEqual(device.raw["top_system"]["id"], "101")


class FilterTests(unittest.TestCase):
    def _devices(self) -> list[AciDevice]:
        nodes = [
            _fabric_node("101", "dc1-leaf-1", "leaf", fabricSt="active"),
            _fabric_node("102", "dc1-leaf-2", "leaf", fabricSt="inactive", model="N9K-C93180YC-FX"),
            _fabric_node("201", "dc1-spine-1", "spine", model="N9K-C9508", version="n9000-16.0(3)"),
            _fabric_node("1101", "dc2-leaf-1", "leaf", pod="2"),
        ]
        systems = [
            _top_system("101", oob="10.1.1.101"),
            _top_system("102", oob="10.1.1.102"),
            _top_system("201", oob="10.1.2.201"),
            _top_system("1101", inb="192.168.5.7"),
        ]
        by_id = {s["id"]: s for s in systems}
        return [d for n in nodes if (d := normalize_device(n, by_id[n["id"]])) is not None]

    def _select(self, **config: Any) -> list[int]:
        flt = AciDeviceFilters.from_config(config)
        return [d.node_id for d in self._devices() if flt.matches(d)]

    def test_empty_filters_match_everything(self) -> None:
        flt = AciDeviceFilters.from_config(None)
        self.assertTrue(flt.is_empty)
        self.assertEqual(self._select(), [101, 102, 201, 1101])

    def test_names_use_star_and_question_mark_wildcards(self) -> None:
        self.assertEqual(self._select(names=["dc1-leaf-*"]), [101, 102])
        self.assertEqual(self._select(names=["dc?-spine-1"]), [201])
        self.assertEqual(self._select(names=["*"]), [101, 102, 201, 1101])

    def test_matching_is_case_sensitive_and_whole_value(self) -> None:
        self.assertEqual(self._select(names=["DC1-leaf-1"]), [])
        self.assertEqual(self._select(names=["leaf"]), [])

    def test_regex_characters_are_literal(self) -> None:
        self.assertEqual(self._select(names=["dc1-leaf-[12]"]), [])
        self.assertEqual(self._select(names=["dc1.leaf.1"]), [])
        self.assertEqual(self._select(names=["dc1-leaf-1|dc1-leaf-2"]), [])

    def test_values_of_one_filter_are_or_different_filters_are_and(self) -> None:
        self.assertEqual(self._select(names=["dc1-leaf-1", "dc1-spine-1"]), [101, 201])
        self.assertEqual(self._select(names=["dc1-*"], roles=["leaf"]), [101, 102])

    def test_roles(self) -> None:
        self.assertEqual(self._select(roles=["spine"]), [201])
        self.assertEqual(self._select(roles=["leaf", "spine"]), [101, 102, 201, 1101])

    def test_pod_and_node_ids(self) -> None:
        self.assertEqual(self._select(pod_ids=[2]), [1101])
        self.assertEqual(self._select(node_ids=[101, 201]), [101, 201])

    def test_models_serials_versions_states(self) -> None:
        self.assertEqual(self._select(models=["N9K-C9508"]), [201])
        self.assertEqual(self._select(models=["N9K-C931*"]), [102])
        self.assertEqual(self._select(models=["N9K-C93*"]), [101, 102, 1101])
        self.assertEqual(self._select(serials=["TEP-1-1*"]), [101, 102, 1101])
        self.assertEqual(self._select(versions=["n9000-*"]), [201])
        self.assertEqual(self._select(fabric_states=["inactive"]), [102])

    def test_cidr_matches_the_management_ip_client_side(self) -> None:
        self.assertEqual(self._select(cidr="10.1.1.0/24"), [101, 102])
        self.assertEqual(self._select(cidr="10.1.2.201/32"), [201])
        self.assertEqual(self._select(cidr="192.168.5.0/24"), [1101])  # in-band fallback

    def test_cidr_never_matches_a_device_without_management_ip(self) -> None:
        node = normalize_device(_fabric_node("301", "no-ip", "leaf"), _top_system("301"))
        assert node is not None
        self.assertFalse(AciDeviceFilters.from_config({"cidr": "0.0.0.0/0"}).matches(node))

    def test_validation_errors(self) -> None:
        bad_configs = [
            {"hostnames": ["x"]},  # unknown key (typo guard)
            {"names": "leaf-1"},  # not a list
            {"names": [1]},  # not text
            {"roles": ["controller"]},  # APIC is out of scope
            {"roles": ["router"]},
            {"pod_ids": ["a"]},
            {"pod_ids": [0]},
            {"node_ids": [True]},
            {"node_ids": [-5]},
            {"cidr": "not-a-cidr"},
            {"cidr": 5},
            {"names": ["x" * 300]},
            {"names": ["bad\x00value"]},
            {"names": [f"n{i}" for i in range(51)]},
        ]
        for config in bad_configs:
            with self.subTest(config=config), self.assertRaises(AciValidationError):
                AciDeviceFilters.from_config(config)
        with self.assertRaises(AciValidationError):
            AciDeviceFilters.from_config(["names"])  # type: ignore[arg-type]

    def test_blank_values_are_dropped_and_duplicates_collapse(self) -> None:
        flt = AciDeviceFilters.from_config({"names": [" a ", "", "a", "b"]})
        self.assertEqual(flt.names, ("a", "b"))

    def test_numeric_strings_are_accepted_for_ids(self) -> None:
        flt = AciDeviceFilters.from_config({"node_ids": ["101", 102], "pod_ids": ["1"]})
        self.assertEqual(flt.node_ids, (101, 102))
        self.assertEqual(flt.pod_ids, (1,))

    def test_blank_lines_in_number_filters_are_ignored_like_in_text_filters(self) -> None:
        # The UI stores a textarea as typed, so blank lines reach the backend.
        flt = AciDeviceFilters.from_config({"node_ids": ["101", "", "  ", "102"], "pod_ids": [""]})
        self.assertEqual(flt.node_ids, (101, 102))
        self.assertEqual(flt.pod_ids, ())
        self.assertTrue(AciDeviceFilters.from_config({"node_ids": ["", " "]}).is_empty)

    def test_cidr_must_be_ipv4_because_management_addresses_are_ipv4(self) -> None:
        for cidr in ("2001:db8::/64", "::/0", "fe80::1"):
            with self.subTest(cidr=cidr), self.assertRaises(AciValidationError) as ctx:
                AciDeviceFilters.from_config({"cidr": cidr})
            self.assertIn("IPv4", str(ctx.exception))
        self.assertEqual(AciDeviceFilters.from_config({"cidr": "10.1.1.0/24"}).cidr, "10.1.1.0/24")

    def test_filters_are_frozen(self) -> None:
        flt = AciDeviceFilters.from_config({"names": ["a"]})
        with self.assertRaises(Exception):  # noqa: B017 - FrozenInstanceError
            flt.names = ()  # type: ignore[misc]


class WildcardMatchTests(unittest.TestCase):
    """``*`` / ``?`` matching must be linear: a pattern is typed by a user and runs in-process."""

    @staticmethod
    def _oracle(pattern: str, value: str) -> bool:
        import re

        regex = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern)
        return re.fullmatch(regex, value, flags=re.DOTALL) is not None

    def test_agrees_with_the_regex_definition_on_every_short_input(self) -> None:
        import itertools

        patterns = ["".join(p) for n in range(0, 6) for p in itertools.product("ab*?", repeat=n)]
        values = ["".join(v) for n in range(0, 6) for v in itertools.product("ab\n", repeat=n)]
        for pattern in patterns:
            for value in values:
                self.assertEqual(
                    _wildcard_match(pattern, value),
                    self._oracle(pattern, value),
                    msg=f"{pattern!r} vs {value!r}",
                )

    def test_many_stars_followed_by_a_missing_literal_do_not_blow_up(self) -> None:
        import time

        started = time.perf_counter()
        for stars in (20, 60, 254):
            self.assertFalse(_wildcard_match("*" * stars + "!", "leaf-101-pod1"))
            self.assertFalse(_wildcard_match("*a" * (stars // 2) + "!", "a" * 200))
        self.assertLess(time.perf_counter() - started, 0.5)

    def test_a_filter_with_the_worst_case_pattern_set_stays_fast(self) -> None:
        import time

        pattern = "*" * 253 + "!"  # + one digit below = 255, the longest value the validator allows
        flt = AciDeviceFilters.from_config({"names": [pattern + str(i % 10) for i in range(50)]})
        devices = [
            normalize_device(_fabric_node(str(100 + i), f"leaf-{i}", "leaf"), None)
            for i in range(200)
        ]
        started = time.perf_counter()
        self.assertEqual([d for d in devices if d is not None and flt.matches(d)], [])
        self.assertLess(time.perf_counter() - started, 2.0)

    def test_none_never_matches_and_star_matches_the_empty_string(self) -> None:
        self.assertFalse(_wildcard_match("*", None))
        self.assertTrue(_wildcard_match("*", ""))
        self.assertFalse(_wildcard_match("?", ""))
        self.assertTrue(_wildcard_match("", ""))


class DeviceServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_returns_sorted_devices_with_one_query_per_class(self) -> None:
        client = _FakeClient(nodes=list(reversed(SANDBOX_NODES)))
        devices = await AciDeviceService(client, CREDS).search()  # type: ignore[arg-type]
        self.assertEqual([d.node_id for d in devices], [101, 102, 201])
        self.assertEqual(
            client.calls,
            [("fabricNode", ROLE_FILTER_FABRIC), ("topSystem", ROLE_FILTER_SYSTEM)],
        )

    async def test_search_narrows_the_server_query_to_the_requested_roles(self) -> None:
        client = _FakeClient()
        filters = AciDeviceFilters.from_config({"roles": ["spine"]})
        devices = await AciDeviceService(client, CREDS).search(filters)  # type: ignore[arg-type]
        self.assertEqual([d.node_id for d in devices], [201])
        self.assertEqual(client.calls[0], ("fabricNode", 'eq(fabricNode.role,"spine")'))
        self.assertEqual(client.calls[1], ("topSystem", 'eq(topSystem.role,"spine")'))

    async def test_search_applies_client_side_filters(self) -> None:
        client = _FakeClient()
        filters = AciDeviceFilters.from_config({"names": ["leaf-*"]})
        devices = await AciDeviceService(client, CREDS).search(filters)  # type: ignore[arg-type]
        self.assertEqual([d.name for d in devices], ["leaf-1", "leaf-2"])

    async def test_controllers_the_server_returns_anyway_are_dropped(self) -> None:
        nodes = [*SANDBOX_NODES, _fabric_node("1", "apic1", "controller")]
        devices = await AciDeviceService(_FakeClient(nodes=nodes), CREDS).search()  # type: ignore[arg-type]
        self.assertEqual([d.node_id for d in devices], [101, 102, 201])

    async def test_management_ips_are_merged_from_top_system(self) -> None:
        systems = [_top_system("101", oob="10.1.1.101"), _top_system("102"), _top_system("201")]
        client = _FakeClient(systems=systems)
        devices = await AciDeviceService(client, CREDS).search()  # type: ignore[arg-type]
        self.assertEqual([d.management_ip for d in devices], ["10.1.1.101", None, None])

    async def test_max_devices_fails_instead_of_truncating(self) -> None:
        service = AciDeviceService(_FakeClient(), CREDS)  # type: ignore[arg-type]
        with self.assertRaises(AciTooManyDevicesError) as ctx:
            await service.search(max_devices=2)
        self.assertEqual(ctx.exception.limit, 2)
        self.assertIsInstance(ctx.exception, AciValidationError)
        self.assertEqual(len(await service.search(max_devices=3)), 3)

    async def test_max_devices_counts_after_filtering(self) -> None:
        filters = AciDeviceFilters.from_config({"roles": ["spine"]})
        service = AciDeviceService(_FakeClient(), CREDS)  # type: ignore[arg-type]
        self.assertEqual(len(await service.search(filters, max_devices=1)), 1)

    async def test_max_devices_must_be_positive(self) -> None:
        service = AciDeviceService(_FakeClient(), CREDS)  # type: ignore[arg-type]
        for bad in (0, -1):
            with self.assertRaises(AciValidationError):
                await service.search(max_devices=bad)

    async def test_client_errors_propagate(self) -> None:
        class Boom(_FakeClient):
            async def query_class(self, *_a, **_k):
                raise AciAPIError("down", code="transport")

        with self.assertRaises(AciAPIError):
            await AciDeviceService(Boom(), CREDS).search()  # type: ignore[arg-type]


class PreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_the_first_matches_and_whether_more_exist(self) -> None:
        service = AciDeviceService(_FakeClient(), CREDS)  # type: ignore[arg-type]
        devices, truncated = await service.preview_devices(AciDeviceFilters(), limit=2)
        self.assertEqual([d.node_id for d in devices], [101, 102])
        self.assertTrue(truncated)

    async def test_not_truncated_when_everything_fits(self) -> None:
        service = AciDeviceService(_FakeClient(), CREDS)  # type: ignore[arg-type]
        devices, truncated = await service.preview_devices(AciDeviceFilters(), limit=3)
        self.assertEqual(len(devices), 3)
        self.assertFalse(truncated)

    async def test_preview_applies_the_filters(self) -> None:
        service = AciDeviceService(_FakeClient(), CREDS)  # type: ignore[arg-type]
        filters = AciDeviceFilters.from_config({"roles": ["spine"]})
        devices, truncated = await service.preview_devices(filters, limit=5)
        self.assertEqual([d.node_id for d in devices], [201])
        self.assertFalse(truncated)

    async def test_limit_must_be_a_positive_whole_number(self) -> None:
        service = AciDeviceService(_FakeClient(), CREDS)  # type: ignore[arg-type]
        for bad in (0, -1, True, 1.5, "3"):
            with self.subTest(limit=bad), self.assertRaises(AciValidationError):
                await service.preview_devices(AciDeviceFilters(), limit=bad)  # type: ignore[arg-type]


class _ConnectionClient:
    def __init__(self, version="6.1(4h)", fail_on=None) -> None:
        self.version = version
        self.fail_on = fail_on
        self.calls: list[tuple] = []

    async def login_info(self, credentials, *, fresh=False):
        self.calls.append(("login_info", fresh))
        if self.fail_on == "login":
            raise AciAPIError("down", code="transport")
        return type("Info", (), {"version": self.version})()

    async def get(self, credentials, path, *, params=None):
        self.calls.append(("get", path, params))
        if self.fail_on == "get":
            raise AciAPIError("forbidden", http_status=403)
        return {"imdata": []}


class TestConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_logs_in_fresh_reads_one_row_and_returns_the_version(self) -> None:
        client = _ConnectionClient()
        version = await AciDeviceService(client, CREDS).test_connection()  # type: ignore[arg-type]
        self.assertEqual(version, "6.1(4h)")
        self.assertEqual(
            client.calls,
            [
                ("login_info", True),
                ("get", "/api/class/fabricNode.json", {"page": 0, "page-size": 1}),
            ],
        )

    async def test_missing_version_is_none(self) -> None:
        for value in (None, ""):
            client = _ConnectionClient(version=value)
            self.assertIsNone(await AciDeviceService(client, CREDS).test_connection())  # type: ignore[arg-type]

    async def test_login_failure_propagates_and_skips_the_read(self) -> None:
        client = _ConnectionClient(fail_on="login")
        with self.assertRaises(AciAPIError):
            await AciDeviceService(client, CREDS).test_connection()  # type: ignore[arg-type]
        self.assertEqual(client.calls, [("login_info", True)])

    async def test_unreadable_inventory_propagates(self) -> None:
        client = _ConnectionClient(fail_on="get")
        with self.assertRaises(AciAPIError):
            await AciDeviceService(client, CREDS).test_connection()  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()

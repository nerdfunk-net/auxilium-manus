"""Batfish read tools for Ask the Net: input bounds, opt-in, source choice, shaping, handles.

A fake reader stands in for the coordinator: nothing here talks to Batfish, the database or
Redis (AI_TOOL_CHAIN.md §10a item 6, §12.6).
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from services.ai_assistant.data_sharing import DataClass, SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore
from services.ai_assistant.tools.base import Toolbox, ToolContext, ToolOutput
from services.ai_assistant.tools.batfish_tools import (
    BATFISH_READER_KEY,
    BatfishAccessError,
    BatfishAnswer,
    BatfishInputError,
    BatfishUnavailableError,
    build_batfish_tools,
)
from services.ai_assistant.tools.envelope import PREVIEW_ROWS
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY

ALL = SharingPolicy(inventory=True, addresses=True, content=True)


class FakeReader:
    def __init__(self) -> None:
        self.sources = ["lab"]
        self.networks = ["net1", "net2"]
        self.snapshots = [
            {"name": "run-2", "created": "2026-11-01T10:00:00Z"},
            {"name": "run-1", "created": "2026-10-01T10:00:00Z"},
        ]
        self.answer = BatfishAnswer(
            rows=[], snapshot="run-2", snapshot_created="2026-11-01T10:00:00Z"
        )
        self.error: Exception | None = None
        self.calls: list[tuple[Any, ...]] = []

    async def list_sources(self) -> list[str]:
        self.calls.append(("list_sources",))
        return self.sources

    async def list_networks(self, source_id: str) -> list[str]:
        self.calls.append(("list_networks", source_id))
        if self.error:
            raise self.error
        return self.networks

    async def list_snapshots(self, source_id: str, network: str) -> list[dict[str, str]]:
        self.calls.append(("list_snapshots", source_id, network))
        if self.error:
            raise self.error
        return self.snapshots

    async def query(
        self, kind: str, source_id: str, network: str, snapshot: str | None, params: dict[str, Any]
    ) -> BatfishAnswer:
        self.calls.append(("query", kind, source_id, network, snapshot, params))
        if self.error:
            raise self.error
        return self.answer


class BatfishToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.reader = FakeReader()
        self.store = ResultStore(InMemoryResultBackend())
        self.ctx = self._ctx(ALL)

    def _ctx(self, sharing: SharingPolicy, user_id: int = 7) -> ToolContext:
        return ToolContext(
            user_id=user_id,
            redactor=Redactor(),
            extras={BATFISH_READER_KEY: self.reader, RESULT_STORE_KEY: self.store},
            sharing=sharing,
        )

    async def _call(
        self, name: str, ctx: ToolContext | None = None, **args: Any
    ) -> tuple[ToolOutput, Any]:
        box = Toolbox(build_batfish_tools(), ctx or self.ctx)
        out = await box.execute(ToolCall(id="1", name=name, input=args))
        try:
            return out, json.loads(out.content)
        except ValueError:
            return out, None

    # -- naming / schema ---------------------------------------------------------------------

    def test_tool_names_follow_the_read_rule(self) -> None:
        names = {t.name for t in build_batfish_tools()}

        self.assertEqual(
            names,
            {
                "list_batfish_networks",
                "list_batfish_snapshots",
                "get_routes",
                "get_traceroute",
                "get_bgp_session_status",
                "get_interface_properties",
                "get_device_facts",
            },
        )
        for name in names:
            self.assertFalse(name.startswith(("run", "trigger", "execute", "start", "delete")))

    def test_every_input_forbids_unknown_fields(self) -> None:
        for tool in build_batfish_tools():
            self.assertIs(tool.input_model.model_config.get("extra"), "forbid", tool.name)

    # -- opt-in ------------------------------------------------------------------------------

    async def test_query_tools_need_the_addresses_opt_in(self) -> None:
        ctx = self._ctx(SharingPolicy(inventory=True))  # addresses off

        for name, args in (
            ("get_routes", {"network": "net1"}),
            ("get_traceroute", {"network": "net1", "node": "r1", "dst_ip": "10.1.2.3"}),
            ("get_bgp_session_status", {"network": "net1"}),
            ("get_interface_properties", {"network": "net1"}),
            ("get_device_facts", {"network": "net1"}),
        ):
            with self.subTest(name):
                out, data = await self._call(name, ctx, **args)
                self.assertEqual(data["not_shared"], "device_addresses")
                self.assertEqual(out.withheld, ("device_addresses",))
        self.assertEqual(self.reader.calls, [])  # nothing was asked of the coordinator

    async def test_discovery_needs_the_inventory_opt_in(self) -> None:
        ctx = self._ctx(SharingPolicy())

        for name, args in (
            ("list_batfish_networks", {}),
            ("list_batfish_snapshots", {"network": "n"}),
        ):
            with self.subTest(name):
                _, data = await self._call(name, ctx, **args)
                self.assertEqual(data["not_shared"], "inventory_data")
        self.assertEqual(self.reader.calls, [])

    # -- source choice -----------------------------------------------------------------------

    async def test_the_only_configured_source_is_used(self) -> None:
        await self._call("get_routes", network="net1")

        self.assertEqual(self.reader.calls[-1][2], "lab")

    async def test_several_sources_without_a_choice_ask_the_model_to_pick(self) -> None:
        self.reader.sources = ["lab", "prod"]

        out, _ = await self._call("get_routes", network="net1")

        self.assertTrue(out.is_error)
        self.assertIn("lab", out.content)
        self.assertIn("prod", out.content)
        self.assertNotIn("query", [c[0] for c in self.reader.calls])

    async def test_an_explicit_source_skips_the_lookup(self) -> None:
        self.reader.sources = ["lab", "prod"]

        await self._call("get_routes", network="net1", source_id="prod")

        self.assertEqual(self.reader.calls[-1][2], "prod")

    async def test_no_configured_source_is_a_clear_error(self) -> None:
        self.reader.sources = []

        out, _ = await self._call("list_batfish_networks")

        self.assertTrue(out.is_error)
        self.assertIn("No Batfish source", out.content)

    # -- error mapping -----------------------------------------------------------------------

    async def test_reader_errors_become_tool_errors_without_internals(self) -> None:
        cases = (
            (BatfishAccessError(), "not available"),
            (BatfishInputError("Batfish network 'x' does not exist"), "does not exist"),
            (BatfishUnavailableError(), "not reachable"),
        )
        for error, expected in cases:
            with self.subTest(type(error).__name__):
                self.reader.error = error
                out, _ = await self._call("get_routes", network="net1")
                self.assertTrue(out.is_error)
                self.assertIn(expected, out.content)

    # -- discovery ---------------------------------------------------------------------------

    async def test_list_networks(self) -> None:
        _, data = await self._call("list_batfish_networks")

        self.assertEqual(data, {"source_id": "lab", "networks": ["net1", "net2"]})

    async def test_list_snapshots_newest_first_and_bounded(self) -> None:
        self.reader.snapshots = [
            {"name": f"run-{i}", "created": f"2026-10-{i:02d}T00:00:00Z"} for i in range(1, 31)
        ]

        _, data = await self._call("list_batfish_snapshots", network="net1")

        self.assertEqual(data["total"], 30)
        self.assertEqual(len(data["snapshots"]), 10)
        self.assertEqual(data["snapshots"][0]["name"], "run-30")

    # -- get_routes --------------------------------------------------------------------------

    async def test_routes_map_arguments_and_default_to_longest_prefix_match(self) -> None:
        await self._call(
            "get_routes", network="net1", nodes=["R1", "r2"], prefix="10.1.2.3", vrf="mgmt"
        )

        _, kind, source, network, snapshot, params = self.reader.calls[-1]
        self.assertEqual((kind, source, network, snapshot), ("routes", "lab", "net1", None))
        self.assertEqual(params["nodes"], "r1,r2")
        self.assertEqual(params["network_prefix"], "10.1.2.3/32")
        self.assertEqual(params["prefix_match_type"], "LONGEST_PREFIX_MATCH")
        self.assertEqual(params["vrfs"], "mgmt")

    async def test_routes_without_a_prefix_send_no_match_type(self) -> None:
        await self._call("get_routes", network="net1")

        params = self.reader.calls[-1][5]
        self.assertIsNone(params["network_prefix"])
        self.assertIsNone(params["prefix_match_type"])
        self.assertIsNone(params["nodes"])

    async def test_routes_result_is_shaped_and_states_what_it_used(self) -> None:
        self.reader.answer = BatfishAnswer(
            rows=[
                {
                    "Node": "r1",
                    "Network": "10.0.0.0/8",
                    "Next_Hop": "x",
                    "Next_Hop_IP": "1.1.1.1",
                    "Junk": 1,
                }
            ],
            snapshot="run-2",
            snapshot_created="2026-11-01T10:00:00Z",
        )

        _, data = await self._call("get_routes", network="net1")

        self.assertEqual(data["rows"], [{"Node": "r1", "Network": "10.0.0.0/8", "Next_Hop": "x"}])
        self.assertEqual(data["network"], "net1")
        self.assertEqual(data["snapshot"], "run-2")
        self.assertEqual(data["snapshot_created"], "2026-11-01T10:00:00Z")

    async def test_big_routing_table_gets_a_handle_and_is_flagged_as_cut(self) -> None:
        self.reader.answer = BatfishAnswer(
            rows=[
                {"Node": f"r{i}", "Network": f"10.{i // 250}.{i % 250}.0/24"} for i in range(300)
            ],
            snapshot="run-2",
            truncated=True,
        )

        out, data = await self._call("get_routes", network="net1")

        self.assertEqual(len(data["rows"]), PREVIEW_ROWS)
        self.assertEqual(data["total_rows"], 300)
        self.assertFalse(data["total_rows_exact"])
        stored = await self.store.get(7, data["handle"])
        assert stored is not None
        self.assertEqual(len(stored.rows or []), 300)
        self.assertTrue(out.truncated)

    async def test_routes_input_validation(self) -> None:
        for bad in (
            {"prefix": "not-an-ip"},
            {"prefix": "10.0.0.0/33"},
            {"nodes": ["r 1"]},
            {"nodes": ["/.*/"]},
            {"nodes": ["r1,r2"]},
            {"nodes": [f"r{i}" for i in range(11)]},
            {"protocols": ["rm -rf"]},
            {"vrf": "a;b"},
            {"prefix_match_type": "regex"},
            {"unknown": 1},
            {"network": ""},
        ):
            with self.subTest(bad):
                out, _ = await self._call("get_routes", **{"network": "net1", **bad})
                self.assertTrue(out.is_error)
        self.assertEqual([c for c in self.reader.calls if c[0] == "query"], [])

    # -- get_traceroute ----------------------------------------------------------------------

    TRACE_ROWS = [
        {
            "Flow": {"srcIp": "192.0.2.1", "dstIp": "10.1.2.3"},
            "Traces": [
                {
                    "disposition": "ACCEPTED",
                    "hops": [{"node": "r1", "steps": [{"action": "ACCEPTED"}]}],
                }
            ],
        }
    ]

    async def test_traceroute_maps_arguments(self) -> None:
        self.reader.answer = BatfishAnswer(rows=self.TRACE_ROWS, snapshot="run-2")

        await self._call(
            "get_traceroute",
            network="net1",
            node="R1",
            dst_ip="10.1.2.3",
            src_ip="192.0.2.1",
            ip_protocol="tcp",
            dst_port=443,
            max_traces=3,
        )

        _, kind, _, _, _, params = self.reader.calls[-1]
        self.assertEqual(kind, "traceroute")
        self.assertEqual(params["start_node"], "r1")
        self.assertEqual(params["dst_ips"], "10.1.2.3")
        self.assertEqual(params["src_ips"], "192.0.2.1")
        self.assertEqual(params["applications"], ["tcp/443"])
        self.assertEqual(params["max_traces"], 3)

    async def test_traceroute_protocol_without_port_uses_ip_protocols(self) -> None:
        self.reader.answer = BatfishAnswer(rows=self.TRACE_ROWS, snapshot="run-2")

        await self._call(
            "get_traceroute", network="net1", node="r1", dst_ip="10.1.2.3", ip_protocol="icmp"
        )

        params = self.reader.calls[-1][5]
        self.assertEqual(params["ip_protocols"], "ICMP")
        self.assertIsNone(params["applications"])

    async def test_traceroute_summary_is_the_default(self) -> None:
        self.reader.answer = BatfishAnswer(rows=self.TRACE_ROWS, snapshot="run-2")

        _, data = await self._call("get_traceroute", network="net1", node="r1", dst_ip="10.1.2.3")

        self.assertEqual(data["rows"][0]["disposition"], "ACCEPTED")
        self.assertEqual(data["rows"][0]["path"], "r1")
        self.assertNotIn("Traces", data["rows"][0])

    async def test_traceroute_structured_format_returns_the_raw_rows(self) -> None:
        self.reader.answer = BatfishAnswer(rows=self.TRACE_ROWS, snapshot="run-2")

        _, data = await self._call(
            "get_traceroute",
            network="net1",
            node="r1",
            dst_ip="10.1.2.3",
            trace_format="structured",
        )

        self.assertIn("Traces", data["rows"][0])

    async def test_unrecognised_trace_shape_is_reported_not_guessed(self) -> None:
        self.reader.answer = BatfishAnswer(
            rows=[{"Flow": "f", "Traces": "Trace(...)"}], snapshot="run-2"
        )

        _, data = await self._call("get_traceroute", network="net1", node="r1", dst_ip="10.1.2.3")

        self.assertIn("could not be summarised", data["note"])
        self.assertEqual(data["rows"][0]["Traces"], "Trace(...)")

    async def test_traceroute_input_validation(self) -> None:
        base = {"network": "net1", "node": "r1", "dst_ip": "10.1.2.3"}
        for bad in (
            {"dst_ip": "10.0.0.0/8"},
            {"dst_ip": "host.example"},
            {"src_ip": "x"},
            {"dst_port": 443},  # a port needs tcp or udp
            {"ip_protocol": "icmp", "dst_port": 8},
            {"ip_protocol": "tcp", "dst_port": 70000},
            {"ip_protocol": "gre"},
            {"max_traces": 0},
            {"max_traces": 11},
            {"trace_format": "raw"},
            {"node": ""},
        ):
            with self.subTest(bad):
                out, _ = await self._call("get_traceroute", **{**base, **bad})
                self.assertTrue(out.is_error)

    # -- get_bgp_session_status --------------------------------------------------------------

    BGP_ROWS = [
        {"Node": "r1", "Remote_Node": "r2", "Established_Status": "ESTABLISHED"},
        {"Node": "r1", "Remote_Node": "r3", "Established_Status": "NOT_ESTABLISHED"},
    ]

    async def test_bgp_returns_counts_and_can_hide_established_sessions(self) -> None:
        self.reader.answer = BatfishAnswer(rows=self.BGP_ROWS, snapshot="run-2")

        _, everything = await self._call("get_bgp_session_status", network="net1")
        _, problems = await self._call("get_bgp_session_status", network="net1", only_problems=True)

        self.assertEqual(len(everything["rows"]), 2)
        self.assertEqual(everything["status_counts"], {"ESTABLISHED": 1, "NOT_ESTABLISHED": 1})
        self.assertEqual([r["Remote_Node"] for r in problems["rows"]], ["r3"])
        self.assertEqual(problems["status_counts"], {"ESTABLISHED": 1, "NOT_ESTABLISHED": 1})

    # -- get_interface_properties ------------------------------------------------------------

    async def test_interfaces_are_flattened_and_the_filter_is_forwarded(self) -> None:
        self.reader.answer = BatfishAnswer(
            rows=[
                {"Interface": {"hostname": "r1", "interface": "Gi0/1"}, "Active": True, "Junk": 1}
            ],
            snapshot="run-2",
        )

        _, data = await self._call(
            "get_interface_properties", network="net1", nodes=["r1"], interface="GigabitEthernet0/1"
        )

        params = self.reader.calls[-1][5]
        self.assertEqual(params["nodes"], "r1")
        self.assertEqual(params["interfaces"], "GigabitEthernet0/1")
        self.assertEqual(data["rows"], [{"Node": "r1", "Interface": "Gi0/1", "Active": True}])

    async def test_interface_name_is_restricted(self) -> None:
        out, _ = await self._call(
            "get_interface_properties", network="net1", interface="Gi0/1; drop"
        )

        self.assertTrue(out.is_error)

    # -- get_device_facts ----------------------------------------------------------------------

    # The shape Batfish really returns (pybatfish NODE_PROPERTIES_REORG): server facts sit under a
    # section name (Syslog, NTP, DNS, SNMP, TACACS), plain facts such as Hostname stay top-level.
    FACT_ROWS = [
        {
            "Node": "r1",
            "Facts": {
                "Hostname": "r1",
                "Syslog": {"Logging_Servers": ["10.9.9.9"], "Logging_Source_Interface": "Lo0"},
                "NTP": {"NTP_Servers": []},
                "IPsec": {"IKE_Phase1_Keys": {"k": "should-never-be-here"}},
                "Interfaces": {"Gi0/1": {"big": "structure"}},
            },
        },
        {
            "Node": "r2",
            "Facts": {
                "Hostname": "r2",
                "Syslog": {"Logging_Servers": []},
                "NTP": {"NTP_Servers": ["1.1.1.1"]},
            },
        },
    ]

    async def test_facts_are_cut_to_the_requested_keys_and_nodes_are_forwarded(self) -> None:
        self.reader.answer = BatfishAnswer(rows=self.FACT_ROWS, snapshot="run-2")

        out, data = await self._call(
            "get_device_facts", network="net1", nodes=["R1", "r2"], facts=["Logging_Servers"]
        )

        self.assertEqual(self.reader.calls[-1][1], "facts")
        self.assertEqual(self.reader.calls[-1][5], {"nodes": "r1,r2"})
        self.assertEqual(
            data["rows"],
            [
                {"Node": "r1", "Logging_Servers": ["10.9.9.9"]},
                {"Node": "r2", "Logging_Servers": []},
            ],
        )
        self.assertNotIn("should-never-be-here", out.content)
        self.assertNotIn("structure", out.content)

    async def test_default_facts_answer_the_management_server_questions(self) -> None:
        self.reader.answer = BatfishAnswer(rows=self.FACT_ROWS, snapshot="run-2")

        _, data = await self._call("get_device_facts", network="net1")

        self.assertEqual(
            data["rows"][0],
            {"Node": "r1", "Hostname": "r1", "Logging_Servers": ["10.9.9.9"], "NTP_Servers": []},
        )

    async def test_summary_counts_the_nodes_that_have_a_value(self) -> None:
        self.reader.answer = BatfishAnswer(rows=self.FACT_ROWS, snapshot="run-2")

        _, data = await self._call(
            "get_device_facts", network="net1", facts=["Logging_Servers", "NTP_Servers"]
        )

        self.assertEqual(
            data["fact_summary"],
            {
                "Logging_Servers": {"nodes_with_values": 1, "nodes_total": 2},
                "NTP_Servers": {"nodes_with_values": 1, "nodes_total": 2},
            },
        )

    async def test_secret_bearing_or_huge_fact_keys_cannot_be_requested(self) -> None:
        for key in ("IKE_Phase1_Keys", "Authentication_Key_Chains", "Interfaces", "Nope"):
            with self.subTest(key):
                out, _ = await self._call("get_device_facts", network="net1", facts=[key])
                self.assertTrue(out.is_error)
        self.assertEqual([c for c in self.reader.calls if c[0] == "query"], [])

    async def test_a_key_no_node_reports_lists_the_keys_batfish_did_return(self) -> None:
        self.reader.answer = BatfishAnswer(
            rows=[
                {
                    "Node": "r1",
                    "Facts": {"Hostname": "r1", "Weird": ["x"], "IPsec": {"IKE_Phase1_Keys": {}}},
                }
            ],
            snapshot="run-2",
        )

        _, data = await self._call("get_device_facts", network="net1", facts=["Logging_Servers"])

        self.assertEqual(data["fact_summary"]["Logging_Servers"]["nodes_with_values"], 0)
        # IPsec stays one opaque name: its inner (key material) names are not folded out.
        self.assertEqual(data["keys_seen"], ["Hostname", "IPsec", "Weird"])
        self.assertIn("not reported", data["note"])

    async def test_fact_values_are_redacted(self) -> None:
        self.reader.answer = BatfishAnswer(
            rows=[{"Node": "r1", "Facts": {"Logging_Servers": ["logserver-secret-xyz"]}}],
            snapshot="run-2",
        )
        self.ctx.redactor.add_known_secrets(["logserver-secret-xyz"])

        out, _ = await self._call("get_device_facts", network="net1", facts=["Logging_Servers"])

        self.assertNotIn("logserver-secret-xyz", out.content)

    async def test_a_fact_inside_its_section_is_found_by_its_plain_name(self) -> None:
        self.reader.answer = BatfishAnswer(
            rows=[
                {
                    "Node": "lab",
                    "Facts": {
                        "Syslog": {
                            "Logging_Servers": ["192.168.178.254"],
                            "Logging_Source_Interface": "Loopback0",
                        }
                    },
                }
            ],
            snapshot="run-2",
        )

        _, data = await self._call(
            "get_device_facts",
            network="net1",
            facts=["Logging_Servers", "Logging_Source_Interface"],
        )

        self.assertEqual(
            data["rows"],
            [
                {
                    "Node": "lab",
                    "Logging_Servers": ["192.168.178.254"],
                    "Logging_Source_Interface": "Loopback0",
                }
            ],
        )
        self.assertEqual(data["fact_summary"]["Logging_Servers"]["nodes_with_values"], 1)
        self.assertNotIn("keys_seen", data)

    async def test_real_lab_facts_answer_the_syslog_question(self) -> None:
        # Values copied from a real extract_facts of the product owner's lab (2026-11-01):
        # only "lab" has a syslog server; lab-2 and switch have an empty list.
        def node(name: str, domain: str, syslog: list[str], tacacs: list[str]) -> dict[str, Any]:
            return {
                "Node": name,
                "Facts": {
                    "Configuration_Format": "CISCO_IOS",
                    "Domain_Name": domain,
                    "Hostname": name,
                    "VRFs": ["default"],
                    "Zones": [],
                    "DNS": {"DNS_Servers": [], "DNS_Source_Interface": None},
                    "NTP": {"NTP_Servers": [], "NTP_Source_Interface": None},
                    "Syslog": {
                        "Logging_Servers": syslog,
                        "Logging_Source_Interface": "Loopback0" if syslog else None,
                    },
                    "SNMP": {"SNMP_Source_Interface": None, "SNMP_Trap_Servers": []},
                    "TACACS": {"TACACS_Servers": tacacs, "TACACS_Source_Interface": None},
                    "OSPF": {"Processes": {}},
                },
            }

        self.reader.answer = BatfishAnswer(
            rows=[
                node("lab", "local.zz", ["192.168.178.254"], ["ISE_SERVER_1"]),
                node("lab-2", "local.zz", [], []),
                node("switch", "lab.zz", [], []),
            ],
            snapshot="run-2",
        )

        _, data = await self._call(
            "get_device_facts",
            network="net1",
            facts=["Logging_Servers", "Logging_Source_Interface", "TACACS_Servers", "Domain_Name"],
        )

        self.assertEqual(
            data["fact_summary"]["Logging_Servers"], {"nodes_with_values": 1, "nodes_total": 3}
        )
        self.assertEqual(
            data["rows"][0],
            {
                "Node": "lab",
                "Logging_Servers": ["192.168.178.254"],
                "Logging_Source_Interface": "Loopback0",
                "TACACS_Servers": ["ISE_SERVER_1"],
                "Domain_Name": "local.zz",
            },
        )
        self.assertEqual(data["rows"][1]["Logging_Servers"], [])
        self.assertNotIn("keys_seen", data)

    # -- audit -------------------------------------------------------------------------------

    async def test_audit_refs_hold_ids_only(self) -> None:
        await self._call("get_routes", network="net1", prefix="10.0.0.1")

        self.assertEqual(self.ctx.audit_refs, {"batfish:lab/net1"})

    # -- review round 2 (doc/analysis/REVIEW.md) ---------------------------------------------

    def _interface_rows(self, n: int) -> list[dict[str, Any]]:
        return [
            {
                "Interface": {"hostname": f"r{i}", "interface": "Gi0/1"},
                "Active": True,
                "Description": "to sw2 pw=hunter2-not-a-pattern",
            }
            for i in range(n)
        ]

    async def test_interface_descriptions_need_the_content_opt_in(self) -> None:
        self.reader.answer = BatfishAnswer(rows=self._interface_rows(25), snapshot="run-2")
        ctx = self._ctx(SharingPolicy(inventory=True, addresses=True))  # content off

        out, data = await self._call("get_interface_properties", ctx, network="net1")

        self.assertNotIn("Description", out.content)
        self.assertNotIn("hunter2", out.content)
        stored = await self.store.get(7, data["handle"])
        assert stored is not None and stored.rows is not None
        self.assertTrue(all("Description" not in row for row in stored.rows))

    async def test_descriptions_are_kept_with_the_content_opt_in_and_the_handle_needs_it_too(
        self,
    ) -> None:
        self.reader.answer = BatfishAnswer(rows=self._interface_rows(25), snapshot="run-2")

        _, data = await self._call("get_interface_properties", network="net1")  # ALL sharing

        self.assertIn("Description", data["rows"][0])
        stored = await self.store.get(7, data["handle"])
        assert stored is not None
        self.assertEqual(stored.data_class, DataClass.CONTENT)
        # The user later switches content sharing off: the handle no longer opens.
        from services.ai_assistant.tools.result_tools import build_result_tools

        ctx = self._ctx(SharingPolicy(inventory=True, addresses=True))
        box = Toolbox(build_result_tools(), ctx)
        out = await box.execute(
            ToolCall(id="2", name="fetch_slice", input={"handle": data["handle"]})
        )
        self.assertEqual(json.loads(out.content)["not_shared"], "content_data")

    async def test_bgp_counts_say_when_they_cover_only_part_of_the_sessions(self) -> None:
        self.reader.answer = BatfishAnswer(rows=self.BGP_ROWS, snapshot="run-2", truncated=True)

        _, data = await self._call("get_bgp_session_status", network="net1", only_problems=True)

        self.assertFalse(data["status_counts_complete"])
        self.assertIn("only the first", data["note"])
        self.assertIn("nodes", data["note"])

    async def test_bgp_counts_are_complete_when_the_answer_was_not_cut(self) -> None:
        self.reader.answer = BatfishAnswer(rows=self.BGP_ROWS, snapshot="run-2")

        _, data = await self._call("get_bgp_session_status", network="net1")

        self.assertTrue(data["status_counts_complete"])
        self.assertNotIn("note", data)

    async def test_names_are_stripped_before_they_reach_the_reader(self) -> None:
        await self._call("get_routes", network="  net1 ", snapshot=" run-2 ")
        await self._call("list_batfish_snapshots", network=" net1\t")

        query = next(c for c in self.reader.calls if c[0] == "query")
        self.assertEqual(query[3:5], ("net1", "run-2"))
        self.assertIn(("list_snapshots", "lab", "net1"), self.reader.calls)


if __name__ == "__main__":
    unittest.main()

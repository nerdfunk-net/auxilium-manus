"""Pure row shaping for the Batfish tools: fewer columns and condensed answers."""

from __future__ import annotations

import copy
import unittest

from services.ai_assistant.tools.batfish_shaping import (
    shape_bgp_sessions,
    shape_interfaces,
    shape_routes,
    summarize_bgp_sessions,
    summarize_traces,
)


def _trace(disposition: str, nodes: list[str], last_action: str = "FORWARDED") -> dict:
    return {
        "disposition": disposition,
        "hops": [
            {"node": n, "steps": [{"action": "RECEIVED"}, {"action": last_action}]} for n in nodes
        ],
    }


class RoutesTests(unittest.TestCase):
    def test_keeps_useful_columns_and_drops_the_rest(self) -> None:
        rows = [
            {
                "Node": "r1",
                "VRF": "default",
                "Network": "10.0.0.0/8",
                "Protocol": "ospf",
                "Next_Hop": {"ip": "1.1.1.1"},
                "Admin_Distance": 110,
                "Metric": 2,
                "Tag": None,
                "Weird_Internal": "x",
            }
        ]

        out = shape_routes(rows)

        self.assertEqual(
            set(out[0]),
            {"Node", "VRF", "Network", "Protocol", "Next_Hop", "Admin_Distance", "Metric", "Tag"},
        )

    def test_legacy_next_hop_columns_are_dropped_when_the_new_one_exists(self) -> None:
        rows = [
            {"Node": "r1", "Next_Hop": "x", "Next_Hop_IP": "1.1.1.1", "Next_Hop_Interface": "Gi0/1"}
        ]

        self.assertEqual(set(shape_routes(rows)[0]), {"Node", "Next_Hop"})

    def test_legacy_columns_stay_when_there_is_no_new_one(self) -> None:
        rows = [{"Node": "r1", "Next_Hop_IP": "1.1.1.1", "Next_Hop_Interface": "Gi0/1"}]

        self.assertEqual(set(shape_routes(rows)[0]), {"Node", "Next_Hop_IP", "Next_Hop_Interface"})

    def test_input_is_not_mutated(self) -> None:
        rows = [{"Node": "r1", "Weird": 1}]
        before = copy.deepcopy(rows)

        shape_routes(rows)

        self.assertEqual(rows, before)


class InterfacesTests(unittest.TestCase):
    def test_nested_interface_identity_is_flattened(self) -> None:
        rows = [
            {
                "Interface": {"hostname": "r1", "interface": "Gi0/1"},
                "Active": True,
                "Primary_Address": "10.0.0.1/24",
                "Junk": 1,
            }
        ]

        out = shape_interfaces(rows)

        self.assertEqual(out[0]["Node"], "r1")
        self.assertEqual(out[0]["Interface"], "Gi0/1")
        self.assertNotIn("Junk", out[0])
        self.assertTrue(out[0]["Active"])

    def test_plain_string_interface_is_kept(self) -> None:
        out = shape_interfaces([{"Interface": "r1[Gi0/1]", "Active": False}])

        self.assertEqual(out[0]["Interface"], "r1[Gi0/1]")
        self.assertNotIn("Node", out[0])


class BgpTests(unittest.TestCase):
    ROWS = [
        {"Node": "r1", "Remote_Node": "r2", "Established_Status": "ESTABLISHED", "Junk": 1},
        {"Node": "r1", "Remote_Node": "r3", "Established_Status": "NOT_ESTABLISHED"},
        {"Node": "r2", "Remote_Node": None, "Established_Status": "NOT_COMPATIBLE"},
    ]

    def test_summary_counts_by_status(self) -> None:
        self.assertEqual(
            summarize_bgp_sessions(self.ROWS),
            {"ESTABLISHED": 1, "NOT_ESTABLISHED": 1, "NOT_COMPATIBLE": 1},
        )

    def test_only_problems_drops_established(self) -> None:
        out = shape_bgp_sessions(self.ROWS, only_problems=True)

        self.assertEqual([r["Remote_Node"] for r in out], ["r3", None])
        self.assertNotIn("Junk", out[0])

    def test_all_sessions_by_default(self) -> None:
        self.assertEqual(len(shape_bgp_sessions(self.ROWS, only_problems=False)), 3)


class TracerouteTests(unittest.TestCase):
    def test_identical_paths_collapse_into_one_row_with_a_count(self) -> None:
        flow = {"srcIp": "192.0.2.1", "dstIp": "10.1.2.3"}
        rows = [
            {"Flow": flow, "Traces": [_trace("ACCEPTED", ["r1", "r2"], "ACCEPTED")]},
            {
                "Flow": {**flow, "srcPort": 1},
                "Traces": [_trace("ACCEPTED", ["r1", "r2"], "ACCEPTED")],
            },
            {"Flow": flow, "Traces": [_trace("NO_ROUTE", ["r1"], "DROPPED")]},
        ]

        out, recognised = summarize_traces(rows)

        self.assertTrue(recognised)
        by_disp = {r["disposition"]: r for r in out}
        self.assertEqual(by_disp["ACCEPTED"]["flows"], 2)
        self.assertEqual(by_disp["ACCEPTED"]["path"], "r1 -> r2")
        self.assertEqual(by_disp["NO_ROUTE"]["path"], "r1")
        self.assertEqual(by_disp["NO_ROUTE"]["last_hop"], "r1")
        self.assertEqual(by_disp["NO_ROUTE"]["last_action"], "DROPPED")
        self.assertEqual(by_disp["NO_ROUTE"]["example_flow"]["dstIp"], "10.1.2.3")

    def test_capitalised_keys_are_understood(self) -> None:
        rows = [
            {
                "Flow": "f",
                "Traces": [{"Disposition": "ACCEPTED", "Hops": [{"Node": "r1", "Steps": []}]}],
            }
        ]

        out, recognised = summarize_traces(rows)

        self.assertTrue(recognised)
        self.assertEqual(out[0]["path"], "r1")

    def test_unknown_shape_is_reported_not_guessed(self) -> None:
        rows = [{"Flow": "f", "Traces": "Trace(disposition=ACCEPTED, ...)"}]

        out, recognised = summarize_traces(rows)

        self.assertFalse(recognised)
        self.assertEqual(out, rows)

    def test_empty_result_is_recognised_as_empty(self) -> None:
        self.assertEqual(summarize_traces([]), ([], True))

    def test_long_paths_are_capped(self) -> None:
        nodes = [f"r{i}" for i in range(80)]
        out, _ = summarize_traces([{"Flow": {}, "Traces": [_trace("LOOP", nodes)]}])

        self.assertLessEqual(out[0]["path"].count("->"), 40)
        self.assertEqual(out[0]["hops"], 80)


if __name__ == "__main__":
    unittest.main()

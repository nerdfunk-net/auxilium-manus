"""Tests for services.batfish.facts_specs: the shared per-node merge/group
engine behind the "combined facts" and "property lookup" Batfish steps and
their ad-hoc preview counterparts.
"""

from __future__ import annotations

import unittest

from services.batfish.facts_specs import (
    CombinedQuestionSpec,
    PropertyQuestionSpec,
    facts_by_node_for_property,
    group_rows_by_node,
    merge_facts_by_node,
)


class GroupRowsByNodeTests(unittest.TestCase):
    def test_groups_rows_by_node_key(self) -> None:
        rows = [{"Node": "r1", "x": 1}, {"Node": "r2", "x": 2}, {"Node": "r1", "x": 3}]
        grouped = group_rows_by_node(rows, node_key=lambda row: row.get("Node"))
        self.assertEqual(
            grouped,
            {
                "r1": [{"Node": "r1", "x": 1}, {"Node": "r1", "x": 3}],
                "r2": [{"Node": "r2", "x": 2}],
            },
        )

    def test_drops_rows_with_no_resolvable_node(self) -> None:
        rows = [{"Node": "r1"}, {}]
        grouped = group_rows_by_node(rows, node_key=lambda row: row.get("Node"))
        self.assertEqual(list(grouped.keys()), ["r1"])


class MergeFactsByNodeTests(unittest.TestCase):
    def _specs(self) -> dict[str, CombinedQuestionSpec]:
        def _strip_node(rows: list[dict]) -> list[dict]:
            return [{k: v for k, v in row.items() if k != "Node"} for row in rows]

        return {
            "process": CombinedQuestionSpec(
                key="process",
                question_label="ospfProcessConfiguration",
                parsed_field="Process",
                node_key=lambda row: row.get("Node"),
                build_group_value=_strip_node,
                row_noun="process row(s)",
            ),
            "areas": CombinedQuestionSpec(
                key="areas",
                question_label="ospfAreaConfiguration",
                parsed_field="Areas",
                node_key=lambda row: row.get("Node"),
                build_group_value=_strip_node,
                row_noun="area row(s)",
            ),
        }

    def test_merges_only_enabled_questions_per_node(self) -> None:
        specs = self._specs()
        rows_by_question = {
            "process": [{"Node": "r1", "VRF": "default"}],
            "areas": [{"Node": "r1", "Area": "0"}, {"Node": "r2", "Area": "1"}],
        }
        result = merge_facts_by_node(specs, rows_by_question)
        self.assertEqual(
            result,
            {
                "r1": {"Process": [{"VRF": "default"}], "Areas": [{"Area": "0"}]},
                "r2": {"Areas": [{"Area": "1"}]},
            },
        )

    def test_disabled_question_absent_from_every_node(self) -> None:
        specs = self._specs()
        rows_by_question = {"process": [{"Node": "r1", "VRF": "default"}]}
        result = merge_facts_by_node(specs, rows_by_question)
        self.assertEqual(result, {"r1": {"Process": [{"VRF": "default"}]}})
        self.assertNotIn("Areas", result["r1"])

    def test_no_rows_returns_empty_dict(self) -> None:
        specs = self._specs()
        result = merge_facts_by_node(specs, {"process": [], "areas": []})
        self.assertEqual(result, {})


class FactsByNodeForPropertyTests(unittest.TestCase):
    def test_groups_and_applies_build_parsed_for_node(self) -> None:
        spec = PropertyQuestionSpec(
            question_label="nodeProperties",
            node_key=lambda row: row.get("Node"),
            build_parsed_for_node=lambda rows: (
                {k: v for k, v in rows[-1].items() if k != "Node"} if rows else {}
            ),
            row_noun="node(s)",
        )
        rows = [{"Node": "r1", "NTP_Servers": ["10.0.0.1"]}, {"Node": "r2", "NTP_Servers": []}]
        result = facts_by_node_for_property(spec, rows)
        self.assertEqual(
            result, {"r1": {"NTP_Servers": ["10.0.0.1"]}, "r2": {"NTP_Servers": []}}
        )

    def test_no_rows_returns_empty_dict(self) -> None:
        spec = PropertyQuestionSpec(
            question_label="nodeProperties",
            node_key=lambda row: row.get("Node"),
            build_parsed_for_node=lambda rows: {},
            row_noun="node(s)",
        )
        self.assertEqual(facts_by_node_for_property(spec, []), {})


if __name__ == "__main__":
    unittest.main()

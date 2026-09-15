"""Tests for the shared Batfish "property lookup" engine
(workflow_steps.common.batfish_properties) -- the pure-logic pieces that
batfish-node-properties/batfish-interface-properties both delegate to.
"""

from __future__ import annotations

import unittest

from models.workflow_context import WorkflowContext
from services.artifacts import InMemoryArtifactService
from workflow_steps.common.batfish_properties import (
    PropertyQuestionSpec,
    build_property_outcomes,
    is_empty_value,
    parse_properties_list,
    row_matches_empty,
    validate_empty_config,
)


class IsEmptyValueTests(unittest.TestCase):
    def test_none_is_empty(self) -> None:
        self.assertTrue(is_empty_value(None))

    def test_blank_and_whitespace_strings_are_empty(self) -> None:
        self.assertTrue(is_empty_value(""))
        self.assertTrue(is_empty_value("   "))

    def test_non_blank_string_is_not_empty(self) -> None:
        self.assertFalse(is_empty_value("tacacs.example.com"))

    def test_empty_collections_are_empty(self) -> None:
        self.assertTrue(is_empty_value([]))
        self.assertTrue(is_empty_value({}))
        self.assertTrue(is_empty_value(()))
        self.assertTrue(is_empty_value(set()))

    def test_non_empty_collection_is_not_empty(self) -> None:
        self.assertFalse(is_empty_value(["10.0.0.5"]))

    def test_falsy_non_empty_scalars_are_not_empty(self) -> None:
        # 0/False are real values, not "unset" -- only None/blank/empty-collection count.
        self.assertFalse(is_empty_value(0))
        self.assertFalse(is_empty_value(False))


class ParsePropertiesListTests(unittest.TestCase):
    def test_splits_trims_and_drops_blanks(self) -> None:
        self.assertEqual(
            parse_properties_list(" TACACS_Servers ,, NTP_Servers,"),
            ["TACACS_Servers", "NTP_Servers"],
        )

    def test_blank_input_returns_empty_list(self) -> None:
        self.assertEqual(parse_properties_list(""), [])


class RowMatchesEmptyTests(unittest.TestCase):
    def test_any_mode_flags_if_at_least_one_property_empty(self) -> None:
        row = {"A": [], "B": ["x"]}
        self.assertTrue(row_matches_empty(row, properties_list=["A", "B"], match_mode="any"))

    def test_all_mode_flags_only_if_every_property_empty(self) -> None:
        row = {"A": [], "B": ["x"]}
        self.assertFalse(row_matches_empty(row, properties_list=["A", "B"], match_mode="all"))
        all_empty_row = {"A": [], "B": []}
        self.assertTrue(
            row_matches_empty(all_empty_row, properties_list=["A", "B"], match_mode="all")
        )


class ValidateEmptyConfigTests(unittest.TestCase):
    def test_route_empty_without_properties_raises(self) -> None:
        with self.assertRaises(ValueError):
            validate_empty_config(
                step_id="batfish-node-properties",
                route_empty_to_devices=True,
                properties_list=[],
                match_mode="any",
            )

    def test_invalid_match_mode_raises(self) -> None:
        with self.assertRaises(ValueError):
            validate_empty_config(
                step_id="batfish-node-properties",
                route_empty_to_devices=False,
                properties_list=["TACACS_Servers"],
                match_mode="sometimes",
            )

    def test_valid_config_does_not_raise(self) -> None:
        validate_empty_config(
            step_id="batfish-node-properties",
            route_empty_to_devices=True,
            properties_list=["TACACS_Servers"],
            match_mode="all",
        )


_TEST_SPEC = PropertyQuestionSpec(
    question_label="nodeProperties",
    node_key=lambda row: row.get("Node"),
    build_parsed_for_node=lambda rows: (
        {key: value for key, value in rows[-1].items() if key != "Node"} if rows else {}
    ),
    row_noun="node(s)",
)


class BuildPropertyOutcomesTests(unittest.IsolatedAsyncioTestCase):
    async def test_stores_artifact_and_enriches_devices(self) -> None:
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        outcomes = await build_property_outcomes(
            spec=_TEST_SPEC,
            rows=[{"Node": "r1", "TACACS_Servers": ["10.0.0.5"]}],
            context=context,
            artifact_service=InMemoryArtifactService(),
            node_id="node-1",
            output_key="batfish_node_properties",
            route_empty_to_devices=False,
            properties_list=[],
            match_mode="any",
        )

        self.assertEqual(outcomes[0].name, "success")
        self.assertEqual(outcomes[0].summary, "1 node(s)")
        result = outcomes[0].context.metadata["node-1.batfish_node_properties"]
        self.assertEqual(result["question"], "nodeProperties")
        self.assertEqual(result["row_count"], 1)

        self.assertEqual(outcomes[1].name, "devices")
        device = outcomes[1].context.devices["r1"]
        self.assertEqual(
            device.parsed["node-1.batfish_node_properties"]["parsed"]["TACACS_Servers"],
            ["10.0.0.5"],
        )

    async def test_route_empty_to_devices_filters_devices_outcome(self) -> None:
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        outcomes = await build_property_outcomes(
            spec=_TEST_SPEC,
            rows=[
                {"Node": "r1", "TACACS_Servers": ["10.0.0.5"]},
                {"Node": "r2", "TACACS_Servers": []},
            ],
            context=context,
            artifact_service=InMemoryArtifactService(),
            node_id="node-1",
            output_key="batfish_node_properties",
            route_empty_to_devices=True,
            properties_list=["TACACS_Servers"],
            match_mode="any",
        )

        devices_outcome = outcomes[1]
        self.assertEqual(set(devices_outcome.context.devices), {"r2"})
        self.assertEqual(devices_outcome.summary, "1 device(s)")


if __name__ == "__main__":
    unittest.main()

"""Tests for the shared OSPF facts merge engine
(workflow_steps.common.batfish_ospf_facts) -- the pure-logic pieces
batfish-ospf-facts' executor delegates to.
"""

from __future__ import annotations

import unittest

from models.workflow_context import Capability, WorkflowContext
from services.artifacts import InMemoryArtifactService
from workflow_steps.common.batfish_ospf_facts import build_ospf_facts_outcomes


class BuildOspfFactsOutcomesTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_four_questions_merge_per_device(self) -> None:
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        rows_by_question = {
            "process": [
                {"Node": "r2", "VRF": "default", "Process_ID": "1", "Router_ID": "2.2.2.2"},
            ],
            "areas": [
                {"Node": "r2", "VRF": "default", "Process_ID": "1", "Area": "0"},
                {"Node": "r2", "VRF": "default", "Process_ID": "1", "Area": "1"},
            ],
            "interfaces": [
                {
                    "Interface": {"hostname": "r2", "interface": "GigabitEthernet0/1"},
                    "OSPF_Enabled": True,
                    "OSPF_Area_Name": 0,
                },
                {
                    "Interface": {"hostname": "r2", "interface": "GigabitEthernet0/2"},
                    "OSPF_Enabled": True,
                    "OSPF_Area_Name": 1,
                },
            ],
            "edges": [
                {
                    "Interface": {"hostname": "r2", "interface": "GigabitEthernet0/1"},
                    "Remote_Interface": {"hostname": "r1", "interface": "GigabitEthernet0/1"},
                },
            ],
        }

        outcomes = await build_ospf_facts_outcomes(
            context=context,
            artifact_service=InMemoryArtifactService(),
            node_id="node-1",
            output_key="batfish_ospf_facts",
            rows_by_question=rows_by_question,
        )

        self.assertEqual(outcomes[0].name, "success")
        self.assertEqual(outcomes[1].name, "devices")
        devices = outcomes[1].context.devices
        self.assertEqual(set(devices), {"r2"})

        device = devices["r2"]
        self.assertEqual(device.capabilities, {Capability.IDENTITY, Capability.PARSED})
        parsed = device.parsed["node-1"]["batfish_ospf_facts"]["parsed"]

        # Process is a list even with one row -- multi-VRF safety.
        self.assertEqual(
            parsed["Process"],
            [{"VRF": "default", "Process_ID": "1", "Router_ID": "2.2.2.2"}],
        )
        # Areas is a list with both of r2's areas -- an ABR must not lose one.
        self.assertEqual(len(parsed["Areas"]), 2)
        self.assertEqual({row["Area"] for row in parsed["Areas"]}, {"0", "1"})
        # Interfaces is a dict keyed by interface name.
        self.assertEqual(
            set(parsed["Interfaces"]), {"GigabitEthernet0/1", "GigabitEthernet0/2"}
        )
        self.assertEqual(parsed["Interfaces"]["GigabitEthernet0/1"]["OSPF_Area_Name"], 0)
        # Adjacencies is a list, including the full row (local + remote interface).
        self.assertEqual(len(parsed["Adjacencies"]), 1)
        self.assertEqual(
            parsed["Adjacencies"][0]["Remote_Interface"],
            {"hostname": "r1", "interface": "GigabitEthernet0/1"},
        )

    async def test_disabled_question_omitted_entirely_not_null(self) -> None:
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        outcomes = await build_ospf_facts_outcomes(
            context=context,
            artifact_service=InMemoryArtifactService(),
            node_id="node-1",
            output_key="batfish_ospf_facts",
            rows_by_question={"process": [{"Node": "r1", "Router_ID": "1.1.1.1"}]},
        )

        devices = outcomes[1].context.devices
        parsed = devices["r1"].parsed["node-1"]["batfish_ospf_facts"]["parsed"]
        self.assertIn("Process", parsed)
        self.assertNotIn("Areas", parsed)
        self.assertNotIn("Interfaces", parsed)
        self.assertNotIn("Adjacencies", parsed)

        # Only one artifact/metadata entry -- for the enabled question.
        metadata = outcomes[0].context.metadata
        self.assertIn("node-1.batfish_ospf_facts.process", metadata)
        self.assertNotIn("node-1.batfish_ospf_facts.areas", metadata)

    async def test_node_identity_union_across_heterogeneous_questions(self) -> None:
        """A node appearing only in one question (e.g. an interface-only OSPF
        edge case) must still surface in devices -- union, not intersection."""
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        outcomes = await build_ospf_facts_outcomes(
            context=context,
            artifact_service=InMemoryArtifactService(),
            node_id="node-1",
            output_key="batfish_ospf_facts",
            rows_by_question={
                "process": [{"Node": "r1", "Router_ID": "1.1.1.1"}],
                "edges": [
                    {
                        "Interface": {"hostname": "r2", "interface": "Gi0/1"},
                        "Remote_Interface": {"hostname": "r3", "interface": "Gi0/1"},
                    }
                ],
            },
        )

        devices = outcomes[1].context.devices
        self.assertEqual(set(devices), {"r1", "r2"})
        self.assertNotIn(
            "Adjacencies", devices["r1"].parsed["node-1"]["batfish_ospf_facts"]["parsed"]
        )
        self.assertNotIn(
            "Process", devices["r2"].parsed["node-1"]["batfish_ospf_facts"]["parsed"]
        )

    async def test_each_enabled_question_stores_its_own_artifact(self) -> None:
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        outcomes = await build_ospf_facts_outcomes(
            context=context,
            artifact_service=InMemoryArtifactService(),
            node_id="node-1",
            output_key="batfish_ospf_facts",
            rows_by_question={
                "process": [{"Node": "r1"}],
                "areas": [{"Node": "r1", "Area": "0"}],
            },
        )

        metadata = outcomes[0].context.metadata
        process_entry = metadata["node-1.batfish_ospf_facts.process"]
        self.assertEqual(process_entry["question"], "ospfProcessConfiguration")
        self.assertEqual(process_entry["row_count"], 1)
        areas_entry = metadata["node-1.batfish_ospf_facts.areas"]
        self.assertEqual(areas_entry["question"], "ospfAreaConfiguration")
        self.assertEqual(areas_entry["row_count"], 1)

    async def test_no_rows_anywhere_yields_empty_devices(self) -> None:
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        outcomes = await build_ospf_facts_outcomes(
            context=context,
            artifact_service=InMemoryArtifactService(),
            node_id="node-1",
            output_key="batfish_ospf_facts",
            rows_by_question={"process": [], "areas": [], "interfaces": [], "edges": []},
        )

        self.assertEqual(outcomes[1].context.devices, {})
        self.assertEqual(outcomes[1].summary, "0 device(s)")


if __name__ == "__main__":
    unittest.main()

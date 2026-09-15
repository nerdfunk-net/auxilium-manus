"""Tests for the shared BGP facts merge engine
(workflow_steps.common.batfish_bgp_facts) -- the pure-logic pieces
batfish-bgp-facts' executor delegates to.
"""

from __future__ import annotations

import unittest

from models.workflow_context import Capability, WorkflowContext
from services.artifacts import InMemoryArtifactService
from workflow_steps.common.batfish_bgp_facts import build_bgp_facts_outcomes


class BuildBgpFactsOutcomesTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_four_questions_merge_per_device(self) -> None:
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        rows_by_question = {
            "process": [{"Node": "r2", "VRF": "default", "Router_ID": "2.2.2.2"}],
            "peers": [
                {"Node": "r2", "VRF": "default", "Local_AS": 200, "Remote_AS": "100"},
                {"Node": "r2", "VRF": "default", "Local_AS": 200, "Remote_AS": "300"},
            ],
            "sessions": [
                {"Node": "r2", "Remote_Node": "r1", "Established_Status": "ESTABLISHED"},
                {"Node": "r2", "Remote_Node": "r3", "Established_Status": "ESTABLISHED"},
            ],
            "edges": [
                {"Node": "r2", "Remote_Node": "r1", "AS_Number": "200", "Remote_AS_Number": "100"},
            ],
        }

        outcomes = await build_bgp_facts_outcomes(
            context=context,
            artifact_service=InMemoryArtifactService(),
            node_id="node-1",
            output_key="batfish_bgp_facts",
            rows_by_question=rows_by_question,
        )

        self.assertEqual(outcomes[0].name, "success")
        self.assertEqual(outcomes[1].name, "devices")
        devices = outcomes[1].context.devices
        self.assertEqual(set(devices), {"r2"})

        device = devices["r2"]
        self.assertEqual(device.capabilities, {Capability.IDENTITY, Capability.PARSED})
        parsed = device.parsed["node-1.batfish_bgp_facts"]["parsed"]

        # Process is a list even with one row -- multi-VRF safety, same as OSPF.
        self.assertEqual(parsed["Process"], [{"VRF": "default", "Router_ID": "2.2.2.2"}])
        # Peers is a list with both of r2's peers.
        self.assertEqual(len(parsed["Peers"]), 2)
        self.assertEqual({row["Remote_AS"] for row in parsed["Peers"]}, {"100", "300"})
        # Sessions is a list with both of r2's sessions.
        self.assertEqual(len(parsed["Sessions"]), 2)
        # Adjacencies is a list, "Node" stripped (redundant with the grouping key).
        self.assertEqual(
            parsed["Adjacencies"],
            [{"Remote_Node": "r1", "AS_Number": "200", "Remote_AS_Number": "100"}],
        )

    async def test_disabled_question_omitted_entirely_not_null(self) -> None:
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        outcomes = await build_bgp_facts_outcomes(
            context=context,
            artifact_service=InMemoryArtifactService(),
            node_id="node-1",
            output_key="batfish_bgp_facts",
            rows_by_question={"process": [{"Node": "r1", "Router_ID": "1.1.1.1"}]},
        )

        devices = outcomes[1].context.devices
        parsed = devices["r1"].parsed["node-1.batfish_bgp_facts"]["parsed"]
        self.assertIn("Process", parsed)
        self.assertNotIn("Peers", parsed)
        self.assertNotIn("Sessions", parsed)
        self.assertNotIn("Adjacencies", parsed)

        metadata = outcomes[0].context.metadata
        self.assertIn("node-1.batfish_bgp_facts.process", metadata)
        self.assertNotIn("node-1.batfish_bgp_facts.peers", metadata)

    async def test_node_identity_union_local_side_only(self) -> None:
        """bgpEdges/bgpSessionStatus rows identify a node via "Node" only --
        a node appearing solely as another node's Remote_Node must not get
        its own device (same rule as ospfEdges' Remote_Interface)."""
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        outcomes = await build_bgp_facts_outcomes(
            context=context,
            artifact_service=InMemoryArtifactService(),
            node_id="node-1",
            output_key="batfish_bgp_facts",
            rows_by_question={
                "process": [{"Node": "r1", "Router_ID": "1.1.1.1"}],
                "edges": [{"Node": "r2", "Remote_Node": "r3", "AS_Number": "200"}],
            },
        )

        devices = outcomes[1].context.devices
        self.assertEqual(set(devices), {"r1", "r2"})
        self.assertNotIn("r3", devices)

    async def test_each_enabled_question_stores_its_own_artifact(self) -> None:
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        outcomes = await build_bgp_facts_outcomes(
            context=context,
            artifact_service=InMemoryArtifactService(),
            node_id="node-1",
            output_key="batfish_bgp_facts",
            rows_by_question={
                "process": [{"Node": "r1"}],
                "peers": [{"Node": "r1", "Remote_AS": "200"}],
            },
        )

        metadata = outcomes[0].context.metadata
        process_entry = metadata["node-1.batfish_bgp_facts.process"]
        self.assertEqual(process_entry["question"], "bgpProcessConfiguration")
        self.assertEqual(process_entry["row_count"], 1)
        peers_entry = metadata["node-1.batfish_bgp_facts.peers"]
        self.assertEqual(peers_entry["question"], "bgpPeerConfiguration")
        self.assertEqual(peers_entry["row_count"], 1)

    async def test_no_rows_anywhere_yields_empty_devices(self) -> None:
        context = WorkflowContext(run_id="run-uuid-1", workflow_id="7")
        outcomes = await build_bgp_facts_outcomes(
            context=context,
            artifact_service=InMemoryArtifactService(),
            node_id="node-1",
            output_key="batfish_bgp_facts",
            rows_by_question={"process": [], "peers": [], "sessions": [], "edges": []},
        )

        self.assertEqual(outcomes[1].context.devices, {})
        self.assertEqual(outcomes[1].summary, "0 device(s)")


if __name__ == "__main__":
    unittest.main()

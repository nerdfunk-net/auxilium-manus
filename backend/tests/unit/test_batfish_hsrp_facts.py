"""HSRP groups from Batfish: hsrpProperties merged into the facts, then built into the bag."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.batfish.credentials import BatfishConnection
from workflow_steps.batfish_extract_facts.executor import execute
from workflow_steps.batfish_extract_facts.hsrp import merge_hsrp_into_facts
from workflow_steps.common.batfish_context import store_batfish_snapshot
from workflow_steps.common.interface_payload import (
    interfaces_from_nautobot_bag,
)
from workflow_steps.config_to_attributes.batfish_facts import build_interfaces_from_batfish_facts

# Real rows of hsrpProperties for the lab switch (Batfish 2026.09, snapshot of run 556).
ROW = {
    "Interface": {"hostname": "switch", "interface": "Vlan200"},
    "Group_Id": 0,
    "Virtual_Addresses": ["192.168.180.100"],
    "Source_Address": "192.168.180.1/24",
    "Priority": 110,
    "Preempt": True,
    "Active": True,
}
DETAILS = {
    "Group_Id": "0",
    "Virtual_Addresses": ["192.168.180.100"],
    "Priority": 110,
    "Preempt": True,
    "Active": True,
}


def _facts() -> dict:
    return {
        "version": "batfish_v0",
        "nodes": {
            "switch": {
                "Interfaces": {
                    "Vlan200": {
                        "Admin_Up": True,
                        "Primary_Address": "192.168.180.1/24",
                        "All_Prefixes": ["192.168.180.1/24"],
                        "HSRP_Groups": ["0"],
                    },
                    "Vlan100": {"Admin_Up": True},
                }
            }
        },
    }


class MergeTests(unittest.TestCase):
    def test_adds_hsrp_details_to_the_interface(self) -> None:
        merged = merge_hsrp_into_facts(_facts(), [ROW])
        vlan = merged["nodes"]["switch"]["Interfaces"]["Vlan200"]
        self.assertEqual(vlan["HSRP_Details"], [DETAILS])
        self.assertNotIn("HSRP_Details", merged["nodes"]["switch"]["Interfaces"]["Vlan100"])

    def test_does_not_mutate_the_input(self) -> None:
        original = _facts()
        snapshot = copy.deepcopy(original)
        merge_hsrp_into_facts(original, [ROW])
        self.assertEqual(original, snapshot)

    def test_two_groups_on_one_interface(self) -> None:
        second = {**ROW, "Group_Id": 5, "Virtual_Addresses": ["192.168.180.105"]}
        merged = merge_hsrp_into_facts(_facts(), [ROW, second])
        groups = merged["nodes"]["switch"]["Interfaces"]["Vlan200"]["HSRP_Details"]
        self.assertEqual([g["Group_Id"] for g in groups], ["0", "5"])

    def test_node_and_interface_match_ignoring_case(self) -> None:
        row = {**ROW, "Interface": {"hostname": "SWITCH", "interface": "vlan200"}}
        merged = merge_hsrp_into_facts(_facts(), [row])
        self.assertIn("HSRP_Details", merged["nodes"]["switch"]["Interfaces"]["Vlan200"])

    def test_unknown_node_interface_or_malformed_rows_are_ignored(self) -> None:
        rows = [
            {**ROW, "Interface": {"hostname": "other", "interface": "Vlan200"}},
            {**ROW, "Interface": {"hostname": "switch", "interface": "Vlan999"}},
            {"Group_Id": 0},
            "junk",
        ]
        self.assertEqual(merge_hsrp_into_facts(_facts(), rows), _facts())

    def test_non_dict_facts_are_returned_unchanged(self) -> None:
        self.assertEqual(merge_hsrp_into_facts({"nodes": None}, [ROW]), {"nodes": None})


def _iface(**extra: object) -> dict:
    node = {
        "Interfaces": {
            "Vlan200": {
                "Admin_Up": True,
                "Primary_Address": "192.168.180.1/24",
                "All_Prefixes": ["192.168.180.1/24"],
                **extra,
            }
        }
    }
    return build_interfaces_from_batfish_facts(node)[0]


class BuilderTests(unittest.TestCase):
    def test_group_built_from_details(self) -> None:
        iface = _iface(HSRP_Details=[DETAILS])
        self.assertEqual(
            iface["interface_redundancy_groups"],
            [
                {
                    "protocol": "HSRP",
                    "protocol_group_id": "0",
                    "virtual_ip": {"address": "192.168.180.100/24"},
                    "preempt": True,
                    "priority": 110,
                }
            ],
        )

    def test_vip_outside_the_interface_subnet_stays_bare(self) -> None:
        details = {**DETAILS, "Virtual_Addresses": ["172.16.0.1"]}
        group = _iface(HSRP_Details=[details])["interface_redundancy_groups"][0]
        self.assertEqual(group["virtual_ip"], {"address": "172.16.0.1"})

    def test_only_group_ids_without_details_gives_no_group(self) -> None:
        self.assertNotIn("interface_redundancy_groups", _iface(HSRP_Groups=["0"]))

    def test_group_without_virtual_address_is_dropped(self) -> None:
        details = {**DETAILS, "Virtual_Addresses": []}
        self.assertNotIn("interface_redundancy_groups", _iface(HSRP_Details=[details]))

    def test_malformed_details_are_ignored(self) -> None:
        self.assertNotIn("interface_redundancy_groups", _iface(HSRP_Details="junk"))
        mixed = _iface(HSRP_Details=["x", {"Group_Id": "0"}])
        self.assertNotIn("interface_redundancy_groups", mixed)

    def test_update_path_reads_the_built_group(self) -> None:
        iface = _iface(HSRP_Details=[DETAILS])
        out = interfaces_from_nautobot_bag({"interfaces": [iface]}, default_prefix_length="/24")
        group = out[0]["interface_redundancy_groups"][0]
        self.assertEqual(group["protocol"], "hsrp")
        self.assertEqual(group["priority"], 110)
        self.assertNotIn("description", group)


class ExtractFactsStepTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, hsrp: AsyncMock, facts: dict | None = None) -> dict:
        outcome = await self._step_outcome(hsrp, facts)
        return outcome.context.devices["d1"].parsed["n1"]["batfish_extract_facts"]["parsed"]

    async def _step_outcome(self, hsrp: AsyncMock, facts: dict | None = None):
        device = DeviceContext(id="d1", name="switch", hostname="switch", status=DeviceStatus.OK)
        context = store_batfish_snapshot(
            WorkflowContext(run_id="run-1", workflow_id="7", devices={"d1": device}),
            connection=BatfishConnection(host="batfish", port=9996),
            network="manus-workflow-7",
            snapshot="run-42",
        )
        with patch("workflow_steps.batfish_extract_facts.executor.service_factory") as factory:
            batfish = MagicMock()
            batfish.extract_facts = AsyncMock(return_value=facts or _facts())
            batfish.hsrp_properties = hsrp
            factory.get_batfish_app_service.return_value = batfish
            outcomes = await execute(
                config={},
                context=context,
                run=MagicMock(id=1),
                artifact_service=InMemoryArtifactService(),
                node_id="n1",
                device_sessions=MagicMock(),
            )
        self.assertEqual(outcomes[0].name, "success")
        return outcomes[0]

    async def test_hsrp_groups_are_merged_into_the_facts(self) -> None:
        parsed = await self._run(AsyncMock(return_value=[ROW]))
        self.assertEqual(parsed["Interfaces"]["Vlan200"]["HSRP_Details"], [DETAILS])

    async def test_hsrp_question_failure_keeps_the_facts_and_says_so(self) -> None:
        parsed = await self._run(AsyncMock(side_effect=RuntimeError("batfish down")))
        self.assertNotIn("HSRP_Details", parsed["Interfaces"]["Vlan200"])
        self.assertEqual(parsed["Interfaces"]["Vlan200"]["HSRP_Groups"], ["0"])
        # The class name only: the text of a Batfish error is the coordinator's, not ours.
        self.assertIn("RuntimeError", parsed["HSRP_Details_Error"])
        self.assertNotIn("batfish down", parsed["HSRP_Details_Error"])

    async def test_hsrp_failure_is_in_the_outcome_summary(self) -> None:
        outcome = await self._step_outcome(AsyncMock(side_effect=RuntimeError("batfish down")))
        self.assertIn("HSRP groups not added", outcome.summary)

    async def test_no_error_marker_without_hsrp_groups_on_the_node(self) -> None:
        facts = _facts()
        facts["nodes"]["switch"]["Interfaces"]["Vlan200"].pop("HSRP_Groups")
        parsed = await self._run(AsyncMock(side_effect=RuntimeError("down")), facts=facts)
        self.assertNotIn("HSRP_Details_Error", parsed)


if __name__ == "__main__":
    unittest.main()

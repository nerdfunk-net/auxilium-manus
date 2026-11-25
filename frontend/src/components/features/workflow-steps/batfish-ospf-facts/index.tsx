"use client";

import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import {
  BatfishCombinedFactsPanel,
  type FactsQuestionToggle,
} from "../shared/batfish-combined-facts-panel";
import { BatfishOspfFactsHelpPanel } from "./help-panel";

const OUTPUT_KEY_DEFAULT = "batfish_ospf_facts";

const QUESTION_TOGGLES: readonly FactsQuestionToggle[] = [
  {
    key: "include_process",
    label: "Process",
    hint: "ospfProcessConfiguration — one row per VRF/process (a node running OSPF in more than one VRF gets more than one row).",
  },
  {
    key: "include_areas",
    label: "Areas",
    hint: "ospfAreaConfiguration — one row per area (an ABR spanning more than one area gets more than one row).",
  },
  {
    key: "include_interfaces",
    label: "Interfaces",
    hint: "ospfInterfaceConfiguration — one row per interface.",
  },
  {
    key: "include_edges",
    label: "Adjacencies",
    hint: "ospfEdges — one row per OSPF adjacency (local + remote interface).",
  },
];

function BatfishOspfFactsConfigPanel(props: PluginConfigPanelProps) {
  return (
    <BatfishCombinedFactsPanel
      {...props}
      toggles={QUESTION_TOGGLES}
      defaultOutputKey={OUTPUT_KEY_DEFAULT}
    />
  );
}

export const BatfishOspfFactsPlugin: PluginUIComponent = {
  ConfigPanel: BatfishOspfFactsConfigPanel,
  HelpPanel: BatfishOspfFactsHelpPanel,
};

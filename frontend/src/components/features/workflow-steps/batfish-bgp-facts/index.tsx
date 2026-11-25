"use client";

import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import {
  BatfishCombinedFactsPanel,
  type FactsQuestionToggle,
} from "../shared/batfish-combined-facts-panel";
import { BatfishBgpFactsHelpPanel } from "./help-panel";

const OUTPUT_KEY_DEFAULT = "batfish_bgp_facts";

const QUESTION_TOGGLES: readonly FactsQuestionToggle[] = [
  {
    key: "include_process",
    label: "Process",
    hint: "bgpProcessConfiguration — one row per VRF (a node running BGP in more than one VRF gets more than one row).",
  },
  {
    key: "include_peers",
    label: "Peers",
    hint: "bgpPeerConfiguration — one row per configured peer.",
  },
  {
    key: "include_sessions",
    label: "Sessions",
    hint: "bgpSessionStatus — one row per BGP session, including established status.",
  },
  {
    key: "include_edges",
    label: "Adjacencies",
    hint: "bgpEdges — one row per BGP adjacency direction.",
  },
];

function BatfishBgpFactsConfigPanel(props: PluginConfigPanelProps) {
  return (
    <BatfishCombinedFactsPanel
      {...props}
      toggles={QUESTION_TOGGLES}
      defaultOutputKey={OUTPUT_KEY_DEFAULT}
    />
  );
}

export const BatfishBgpFactsPlugin: PluginUIComponent = {
  ConfigPanel: BatfishBgpFactsConfigPanel,
  HelpPanel: BatfishBgpFactsHelpPanel,
};

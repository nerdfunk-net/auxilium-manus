"use client";

import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { BatfishDirectTargetFields } from "../shared/batfish-direct-target-fields";
import { BatfishBgpFactsHelpPanel } from "./help-panel";

const OUTPUT_KEY_DEFAULT = "batfish_bgp_facts";

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

interface QuestionToggle {
  key: string;
  label: string;
  hint: string;
}

const QUESTION_TOGGLES: QuestionToggle[] = [
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

function BatfishBgpFactsConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const nodes = stringFromConfig(config, "nodes");
  const outputKey = stringFromConfig(config, "output_key");

  const handleNodesChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) =>
      onChange({ ...config, nodes: event.target.value }),
    [config, onChange],
  );

  const handleOutputKeyChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) =>
      onChange({ ...config, output_key: event.target.value }),
    [config, onChange],
  );

  const handleToggleChange = useCallback(
    (key: string, checked: boolean) => onChange({ ...config, [key]: checked }),
    [config, onChange],
  );

  const enabledCount = QUESTION_TOGGLES.filter((toggle) => config[toggle.key] !== false).length;

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">nodes</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={nodes}
          onChange={handleNodesChange}
          placeholder="e.g. R1"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Optional. Applied to every enabled question below. Leave empty to return facts for
          every node.
        </p>
      </div>

      <div className="space-y-1.5 border-t pt-3">
        <span className="font-mono text-xs font-medium">Questions</span>
        <p className="text-[11px] leading-4 text-muted-foreground">
          At least one must stay enabled.
        </p>
        <div className="space-y-2 pt-1">
          {QUESTION_TOGGLES.map((toggle) => {
            const checked = config[toggle.key] !== false;
            return (
              <label key={toggle.key} className="flex items-start gap-1.5 text-xs">
                <Checkbox
                  className="mt-0.5"
                  checked={checked}
                  onCheckedChange={(value) => handleToggleChange(toggle.key, value === true)}
                  disabled={checked && enabledCount === 1}
                />
                <span>
                  <span className="font-medium">{toggle.label}</span>
                  <p className="text-[11px] leading-4 text-muted-foreground">{toggle.hint}</p>
                </span>
              </label>
            );
          })}
        </div>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">output_key</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={outputKey}
          onChange={handleOutputKeyChange}
          placeholder={OUTPUT_KEY_DEFAULT}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Each enabled question is stored as its own result artifact under this key; the{" "}
          <span className="font-mono">devices</span> outcome merges all enabled questions into
          one combined payload per device.
        </p>
      </div>

      <BatfishDirectTargetFields config={config} onChange={onChange} />
    </div>
  );
}

export const BatfishBgpFactsPlugin: PluginUIComponent = {
  ConfigPanel: BatfishBgpFactsConfigPanel,
  HelpPanel: BatfishBgpFactsHelpPanel,
};

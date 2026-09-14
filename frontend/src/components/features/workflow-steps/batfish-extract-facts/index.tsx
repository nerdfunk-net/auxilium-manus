"use client";

import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { BatfishDirectTargetFields } from "../shared/batfish-direct-target-fields";
import { BatfishExtractFactsHelpPanel } from "./help-panel";

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function BatfishExtractFactsConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const nodesFilter = stringFromConfig(config, "nodes_filter");
  const outputKey = stringFromConfig(config, "output_key");

  const handleFieldChange = useCallback(
    (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [key]: event.target.value });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">nodes_filter</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={nodesFilter}
          onChange={handleFieldChange("nodes_filter")}
          placeholder="(this run's devices)"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          NodeSpecifier (e.g. &quot;/^r/&quot; or &quot;node1|node2&quot;). Leave blank to
          default to exactly this run&apos;s devices; set to &quot;/.*/&quot; explicitly to
          extract every node in the snapshot.
        </p>
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
          onChange={handleFieldChange("output_key")}
          placeholder="batfish_extract_facts"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Each device&apos;s own extracted facts are written to{" "}
          device.parsed under this key; the full result is also stored as one workflow-level
          artifact under this key in the run&apos;s metadata.
        </p>
      </div>

      <BatfishDirectTargetFields config={config} onChange={onChange} />
    </div>
  );
}

export const BatfishExtractFactsPlugin: PluginUIComponent = {
  ConfigPanel: BatfishExtractFactsConfigPanel,
  HelpPanel: BatfishExtractFactsHelpPanel,
};

"use client";

import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { BatfishDirectTargetFields } from "../shared/batfish-direct-target-fields";
import { GetBatfishDevicesHelpPanel } from "./help-panel";

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function GetBatfishDevicesConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const nodesFilter = stringFromConfig(config, "nodes_filter");

  const handleFieldChange = useCallback(
    (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [key]: event.target.value });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground">
        With no config and no upstream Init Batfish Snapshot on this run, this step clears
        devices to an empty placeholder — no Batfish contact — purely to satisfy the canvas&apos;s
        connection rule. Once this run&apos;s own Init Batfish Snapshot has run, or a network is
        targeted directly below, this step instead lists that snapshot&apos;s nodes as devices.
      </div>

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
          placeholder="/.*/  (every node)"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          NodeSpecifier restricting which nodes are listed as devices (e.g. &quot;/^r/&quot; or
          &quot;node1|node2&quot;). Leave blank to list every node in the snapshot. Only used
          when this step actually queries Batfish (see above).
        </p>
      </div>

      <BatfishDirectTargetFields config={config} onChange={onChange} />
    </div>
  );
}

export const GetBatfishDevicesPlugin: PluginUIComponent = {
  ConfigPanel: GetBatfishDevicesConfigPanel,
  HelpPanel: GetBatfishDevicesHelpPanel,
};

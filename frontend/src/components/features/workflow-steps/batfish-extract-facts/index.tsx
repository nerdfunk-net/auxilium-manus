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
import { BatfishExtractFactsHelpPanel } from "./help-panel";

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

const USE_SHORT_HOSTNAME_KEY = "use_short_hostname";

function BatfishExtractFactsConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const nodesFilter = stringFromConfig(config, "nodes_filter");
  const outputKey = stringFromConfig(config, "output_key");

  const useShortHostname = config[USE_SHORT_HOSTNAME_KEY] !== false;

  const handleShortHostnameChange = useCallback(
    (checked: boolean) => {
      onChange({ ...config, [USE_SHORT_HOSTNAME_KEY]: checked });
    },
    [config, onChange],
  );

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

      <label className="flex items-start gap-1.5 text-xs font-medium">
        <Checkbox
          className="mt-0.5"
          checked={useShortHostname}
          onCheckedChange={(checked) => handleShortHostnameChange(checked === true)}
        />
        <span>
          <span className="font-mono">{USE_SHORT_HOSTNAME_KEY}</span>
          <span className="block text-[11px] font-normal leading-4 text-muted-foreground">
            Look devices up by the part of their name before the first dot (
            <span className="font-mono">lab.local.zz</span> →{" "}
            <span className="font-mono">lab</span>). On (default) suits configs with a short{" "}
            <span className="font-mono">hostname</span> while the inventory stores FQDNs. Turn off
            when the configs use the FQDN as hostname: the full lowercased name is used.
          </span>
        </span>
      </label>

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

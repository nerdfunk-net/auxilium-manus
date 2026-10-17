"use client";

import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { BatfishDirectTargetFields } from "../shared/batfish-direct-target-fields";
import { BatfishRoutingTableHelpPanel } from "./help-panel";

const PREFIX_MATCH_TYPE_KEY = "prefix_match_type";
const RIB_KEY = "rib";
const DEFAULT_PREFIX_MATCH_TYPE = "EXACT";
const DEFAULT_RIB = "main";

const PREFIX_MATCH_TYPES = [
  "EXACT",
  "LONGEST_PREFIX_MATCH",
  "LONGER_PREFIXES",
  "SHORTER_PREFIXES",
] as const;

const RIBS = ["main", "bgp", "evpn"] as const;

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function BatfishRoutingTableConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const nodes = stringFromConfig(config, "nodes");
  const networkPrefix = stringFromConfig(config, "network_prefix");
  const prefixMatchType = stringFromConfig(config, PREFIX_MATCH_TYPE_KEY) || DEFAULT_PREFIX_MATCH_TYPE;
  const protocols = stringFromConfig(config, "protocols");
  const vrfs = stringFromConfig(config, "vrfs");
  const rib = stringFromConfig(config, RIB_KEY) || DEFAULT_RIB;
  const outputKey = stringFromConfig(config, "output_key");

  const handleFieldChange = useCallback(
    (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [key]: event.target.value });
    },
    [config, onChange],
  );

  const handlePrefixMatchTypeChange = useCallback(
    (value: string) => onChange({ ...config, [PREFIX_MATCH_TYPE_KEY]: value }),
    [config, onChange],
  );

  const handleRibChange = useCallback(
    (value: string) => onChange({ ...config, [RIB_KEY]: value }),
    [config, onChange],
  );

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
          onChange={handleFieldChange("nodes")}
          placeholder="e.g. R1"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Optional. Leave empty to return routes on every node.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">network_prefix</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={networkPrefix}
          onChange={handleFieldChange("network_prefix")}
          placeholder="e.g. 192.168.1.0/24"
          className="h-8 font-mono text-xs"
        />
      </div>

      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{PREFIX_MATCH_TYPE_KEY}</span>
        <Select value={prefixMatchType} onValueChange={handlePrefixMatchTypeChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder="EXACT" />
          </SelectTrigger>
          <SelectContent>
            {PREFIX_MATCH_TYPES.map((value) => (
              <SelectItem key={value} value={value}>
                {value}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">protocols</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={protocols}
          onChange={handleFieldChange("protocols")}
          placeholder="e.g. static, bgp"
          className="h-8 font-mono text-xs"
        />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">vrfs</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={vrfs}
          onChange={handleFieldChange("vrfs")}
          placeholder="e.g. default"
          className="h-8 font-mono text-xs"
        />
      </div>

      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{RIB_KEY}</span>
        <Select value={rib} onValueChange={handleRibChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder="main" />
          </SelectTrigger>
          <SelectContent>
            {RIBS.map((value) => (
              <SelectItem key={value} value={value}>
                {value}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
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
          placeholder="batfish_routes"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          The result — a JSON artifact plus a row count — is stored under{" "}
          this key in the run&apos;s metadata (not per-device).
        </p>
      </div>

      <BatfishDirectTargetFields config={config} onChange={onChange} />
    </div>
  );
}

export const BatfishRoutingTablePlugin: PluginUIComponent = {
  ConfigPanel: BatfishRoutingTableConfigPanel,
  HelpPanel: BatfishRoutingTableHelpPanel,
};

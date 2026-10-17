"use client";

import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { BatfishDirectTargetFields } from "../shared/batfish-direct-target-fields";
import { BatfishPathCheckHelpPanel } from "./help-panel";

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function numberFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "number" ? String(raw) : typeof raw === "string" ? raw : "";
}

function boolFromConfig(config: Record<string, unknown>, key: string): boolean {
  return config[key] === true;
}

function applicationsFromConfig(config: Record<string, unknown>): string {
  const raw = config.applications;
  return Array.isArray(raw)
    ? raw.filter((item): item is string => typeof item === "string").join(", ")
    : "";
}

function BatfishPathCheckConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const startNode = stringFromConfig(config, "start_node");
  const endNode = stringFromConfig(config, "end_node");
  const dstIps = stringFromConfig(config, "dst_ips");
  const srcIps = stringFromConfig(config, "src_ips");
  const applications = applicationsFromConfig(config);
  const ipProtocols = stringFromConfig(config, "ip_protocols");
  const maxTraces = numberFromConfig(config, "max_traces");
  const invertSearch = boolFromConfig(config, "invert_search");
  const ignoreFilters = boolFromConfig(config, "ignore_filters");
  const outputKey = stringFromConfig(config, "output_key");

  const handleFieldChange = useCallback(
    (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [key]: event.target.value });
    },
    [config, onChange],
  );

  const handleMaxTracesChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const value = event.target.value;
      const parsed = Number.parseInt(value, 10);
      onChange({ ...config, max_traces: Number.isNaN(parsed) ? value : parsed });
    },
    [config, onChange],
  );

  const handleApplicationsChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const applicationsList = event.target.value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      onChange({ ...config, applications: applicationsList });
    },
    [config, onChange],
  );

  const handleInvertSearchChange = useCallback(
    (checked: boolean) => onChange({ ...config, invert_search: checked }),
    [config, onChange],
  );

  const handleIgnoreFiltersChange = useCallback(
    (checked: boolean) => onChange({ ...config, ignore_filters: checked }),
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">start_node</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={startNode}
          onChange={handleFieldChange("start_node")}
          placeholder="e.g. R1"
          className="h-8 font-mono text-xs"
        />
        {startNode ? null : (
          <p className="text-[11px] text-warning-foreground">Required</p>
        )}
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">end_node</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={endNode}
          onChange={handleFieldChange("end_node")}
          placeholder="e.g. R2"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Leave empty to search any destination.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">dst_ips</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={dstIps}
          onChange={handleFieldChange("dst_ips")}
          placeholder="e.g. 192.168.1.1"
          className="h-8 font-mono text-xs"
        />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">src_ips</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={srcIps}
          onChange={handleFieldChange("src_ips")}
          placeholder="e.g. 10.0.0.1"
          className="h-8 font-mono text-xs"
        />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">applications</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            array
          </Badge>
        </div>
        <Input
          value={applications}
          onChange={handleApplicationsChange}
          placeholder="e.g. SSH, HTTPS"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Comma-separated named applications.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">ip_protocols</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={ipProtocols}
          onChange={handleFieldChange("ip_protocols")}
          placeholder="e.g. tcp"
          className="h-8 font-mono text-xs"
        />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">max_traces</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            integer
          </Badge>
        </div>
        <Input
          type="number"
          min={1}
          value={maxTraces}
          onChange={handleMaxTracesChange}
          className="h-8 font-mono text-xs"
        />
      </div>

      <div className="flex items-center justify-between">
        <span className="font-mono text-xs font-medium">invert_search</span>
        <Switch checked={invertSearch} onCheckedChange={handleInvertSearchChange} />
      </div>

      <div className="flex items-center justify-between">
        <span className="font-mono text-xs font-medium">ignore_filters</span>
        <Switch checked={ignoreFilters} onCheckedChange={handleIgnoreFiltersChange} />
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
          placeholder="batfish_path_check"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          The result — a JSON artifact plus the reachable flag — is stored
          under this key in the run&apos;s metadata (not per-device).
        </p>
      </div>

      <BatfishDirectTargetFields config={config} onChange={onChange} />
    </div>
  );
}

export const BatfishPathCheckPlugin: PluginUIComponent = {
  ConfigPanel: BatfishPathCheckConfigPanel,
  HelpPanel: BatfishPathCheckHelpPanel,
};

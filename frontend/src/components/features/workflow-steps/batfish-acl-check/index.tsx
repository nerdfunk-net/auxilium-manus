"use client";

import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { BatfishAclCheckHelpPanel } from "./help-panel";

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function applicationsFromConfig(config: Record<string, unknown>): string {
  const raw = config.applications;
  return Array.isArray(raw)
    ? raw.filter((item): item is string => typeof item === "string").join(", ")
    : "";
}

function RequiredField({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  placeholder: string;
  onChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs font-medium">{label}</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          string
        </Badge>
      </div>
      <Input
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        className="h-8 font-mono text-xs"
      />
      {value ? null : <p className="text-[11px] text-warning-foreground">Required</p>}
    </div>
  );
}

function BatfishAclCheckConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const node = stringFromConfig(config, "node");
  const filterName = stringFromConfig(config, "filter_name");
  const dstIps = stringFromConfig(config, "dst_ips");
  const srcIps = stringFromConfig(config, "src_ips");
  const applications = applicationsFromConfig(config);
  const ipProtocols = stringFromConfig(config, "ip_protocols");
  const startLocation = stringFromConfig(config, "start_location");
  const outputKey = stringFromConfig(config, "output_key");

  const handleFieldChange = useCallback(
    (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [key]: event.target.value });
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

  return (
    <div className="flex flex-col gap-4">
      <RequiredField
        label="node"
        value={node}
        placeholder="e.g. R1"
        onChange={handleFieldChange("node")}
      />

      <RequiredField
        label="filter_name"
        value={filterName}
        placeholder="e.g. TEST-ACL"
        onChange={handleFieldChange("filter_name")}
      />

      <RequiredField
        label="dst_ips"
        value={dstIps}
        placeholder="e.g. 192.168.1.1"
        onChange={handleFieldChange("dst_ips")}
      />

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
          placeholder="e.g. 8.8.8.8"
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
          placeholder="e.g. SSH, TELNET"
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
          <span className="font-mono text-xs font-medium">start_location</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={startLocation}
          onChange={handleFieldChange("start_location")}
          placeholder="optional"
          className="h-8 font-mono text-xs"
        />
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
          placeholder="batfish_acl_check"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          The result — a JSON artifact plus the matched action — is stored
          under this key in the run&apos;s metadata (not per-device).
        </p>
      </div>
    </div>
  );
}

export const BatfishAclCheckPlugin: PluginUIComponent = {
  ConfigPanel: BatfishAclCheckConfigPanel,
  HelpPanel: BatfishAclCheckHelpPanel,
};

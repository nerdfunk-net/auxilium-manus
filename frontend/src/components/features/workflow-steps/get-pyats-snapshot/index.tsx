"use client";

import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { GetPyatsSnapshotHelpPanel } from "./help-panel";

const OUTPUT_KEY = "output_key";
const FEATURES_KEY = "features";
const ALL_FEATURES_VALUE = "all";

interface FeatureOption {
  value: string;
  label: string;
}

interface FeatureGroup {
  label: string;
  options: FeatureOption[];
}

const FEATURE_GROUPS: FeatureGroup[] = [
  {
    label: "Routing & Switching Protocols",
    options: [
      { value: "bgp", label: "bgp" },
      { value: "ospf", label: "ospf" },
      { value: "eigrp", label: "eigrp" },
      { value: "rip", label: "rip" },
      { value: "isis", label: "isis" },
      { value: "pim", label: "pim" },
      { value: "igmp", label: "igmp" },
    ],
  },
  {
    label: "Services & Layer 2/3 Features",
    options: [
      { value: "vlan", label: "vlan" },
      { value: "stp", label: "stp" },
      { value: "lldp", label: "lldp" },
      { value: "cdp", label: "cdp" },
      { value: "arp", label: "arp" },
      { value: "dhcp", label: "dhcp" },
      { value: "nat", label: "nat" },
      { value: "acl", label: "acl" },
      { value: "vrf", label: "vrf" },
    ],
  },
  {
    label: "System & Platform Attributes",
    options: [
      { value: "interface", label: "interface" },
      { value: "platform", label: "platform" },
      { value: "routing", label: "routing" },
      { value: "config", label: "config" },
    ],
  },
];

function outputKeyFromConfig(config: Record<string, unknown>): string {
  return typeof config[OUTPUT_KEY] === "string" ? (config[OUTPUT_KEY] as string) : "";
}

function featuresFromConfig(config: Record<string, unknown>): string[] {
  const raw = config[FEATURES_KEY];
  return Array.isArray(raw) ? raw.filter((item): item is string => typeof item === "string") : [];
}

function GetPyatsSnapshotConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const outputKey = outputKeyFromConfig(config);
  const features = featuresFromConfig(config);
  const allSelected = features.includes(ALL_FEATURES_VALUE);

  const handleOutputKeyChange = useCallback(
    (value: string) => {
      onChange({ ...config, [OUTPUT_KEY]: value });
    },
    [config, onChange],
  );

  const toggleAll = useCallback(
    (checked: boolean) => {
      onChange({ ...config, [FEATURES_KEY]: checked ? [ALL_FEATURES_VALUE] : [] });
    },
    [config, onChange],
  );

  const toggleFeature = useCallback(
    (value: string, checked: boolean) => {
      const current = new Set(features.filter((item) => item !== ALL_FEATURES_VALUE));
      if (checked) {
        current.add(value);
      } else {
        current.delete(value);
      }
      onChange({ ...config, [FEATURES_KEY]: Array.from(current) });
    },
    [config, features, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{FEATURES_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            array
          </Badge>
        </div>

        <label className="flex items-center gap-1.5 text-xs font-medium">
          <Checkbox
            checked={allSelected}
            onCheckedChange={(checked) => toggleAll(checked === true)}
          />
          all (learn everything supported)
        </label>

        <div className={allSelected ? "space-y-2 opacity-50" : "space-y-2"}>
          {FEATURE_GROUPS.map((group) => (
            <div key={group.label} className="space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                {group.label}
              </p>
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                {group.options.map((option) => (
                  <label key={option.value} className="flex items-center gap-1.5 text-xs">
                    <Checkbox
                      checked={features.includes(option.value)}
                      disabled={allSelected}
                      onCheckedChange={(checked) => toggleFeature(option.value, checked === true)}
                    />
                    {option.label}
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>

        {features.length === 0 ? (
          <p className="text-[11px] text-warning-foreground">
            Select at least one feature, or &quot;all&quot;
          </p>
        ) : null}
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{OUTPUT_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={outputKey}
          onChange={(event) => handleOutputKeyChange(event.target.value)}
          placeholder="pyats_snapshot"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Downstream steps reference this key in{" "}
          <span className="font-mono">device.parsed.{outputKey || "output_key"}</span>.
        </p>
      </div>
    </div>
  );
}

export const GetPyatsSnapshotPlugin: PluginUIComponent = {
  ConfigPanel: GetPyatsSnapshotConfigPanel,
  HelpPanel: GetPyatsSnapshotHelpPanel,
};

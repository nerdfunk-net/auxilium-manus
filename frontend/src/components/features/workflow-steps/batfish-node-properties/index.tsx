"use client";

import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
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

import { BATFISH_FACT_KEYS } from "../shared/batfish-fact-keys";
import { BatfishDirectTargetFields } from "../shared/batfish-direct-target-fields";
import { BatfishNodePropertiesHelpPanel } from "./help-panel";

const ROUTE_EMPTY_KEY = "route_empty_to_devices";
const EMPTY_MATCH_MODE_KEY = "empty_match_mode";
const DEFAULT_EMPTY_MATCH_MODE = "any";

const EMPTY_MATCH_MODES = ["any", "all"] as const;

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function parsePropertiesList(properties: string): string[] {
  return properties
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

function BatfishNodePropertiesConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const nodes = stringFromConfig(config, "nodes");
  const properties = stringFromConfig(config, "properties");
  const outputKey = stringFromConfig(config, "output_key");
  const routeEmptyToDevices = config[ROUTE_EMPTY_KEY] === true;
  const emptyMatchMode = stringFromConfig(config, EMPTY_MATCH_MODE_KEY) || DEFAULT_EMPTY_MATCH_MODE;
  const propertiesList = parsePropertiesList(properties);

  const handleFieldChange = useCallback(
    (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [key]: event.target.value });
    },
    [config, onChange],
  );

  const handlePropertySuggestionClick = useCallback(
    (property: string) => {
      const existing = propertiesList;
      if (existing.includes(property)) return;
      onChange({ ...config, properties: [...existing, property].join(", ") });
    },
    [config, onChange, propertiesList],
  );

  const handleRouteEmptyToDevicesChange = useCallback(
    (checked: boolean) => onChange({ ...config, [ROUTE_EMPTY_KEY]: checked }),
    [config, onChange],
  );

  const handleEmptyMatchModeChange = useCallback(
    (value: string) => onChange({ ...config, [EMPTY_MATCH_MODE_KEY]: value }),
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
          Optional. Leave empty to return properties for every node.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">properties</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={properties}
          onChange={handleFieldChange("properties")}
          placeholder="e.g. TACACS_Servers, TACACS_Source_Interface"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Optional, comma-separated. Leave empty to return Batfish&apos;s own
          default column set.
        </p>
        <div className="flex flex-wrap gap-1 pt-0.5">
          {BATFISH_FACT_KEYS.map((property) => (
            <button
              key={property}
              type="button"
              onClick={() => handlePropertySuggestionClick(property)}
              className="rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground transition-colors hover:border-primary hover:text-foreground"
            >
              {property}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-1.5 border-t pt-3">
        <label className="flex items-center gap-1.5 text-xs font-medium">
          <Checkbox
            checked={routeEmptyToDevices}
            onCheckedChange={(checked) => handleRouteEmptyToDevicesChange(checked === true)}
          />
          Route empty set to Devices
        </label>
        <p className="text-[11px] leading-4 text-muted-foreground">
          When enabled, the <span className="font-mono">devices</span> outcome
          only carries nodes whose requested properties are empty — e.g. an
          unconfigured TACACS server, which Batfish reports as{" "}
          <span className="font-mono">TACACS_Servers: []</span> rather than a
          missing row. Requires <span className="font-mono">properties</span>{" "}
          above to be set.
        </p>

        {routeEmptyToDevices && propertiesList.length > 1 && (
          <div className="space-y-1.5 pt-1">
            <span className="font-mono text-xs font-medium">{EMPTY_MATCH_MODE_KEY}</span>
            <Select value={emptyMatchMode} onValueChange={handleEmptyMatchModeChange}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue placeholder="any" />
              </SelectTrigger>
              <SelectContent>
                {EMPTY_MATCH_MODES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {value}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-[11px] leading-4 text-muted-foreground">
              With more than one property configured: <span className="font-mono">any</span>{" "}
              (default) routes a device if at least one requested property is
              empty; <span className="font-mono">all</span> routes it only if
              every requested property is empty.
            </p>
          </div>
        )}
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
          placeholder="batfish_node_properties"
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

export const BatfishNodePropertiesPlugin: PluginUIComponent = {
  ConfigPanel: BatfishNodePropertiesConfigPanel,
  HelpPanel: BatfishNodePropertiesHelpPanel,
};

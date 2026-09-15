"use client";

import { useCallback, type ReactNode } from "react";

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

import { BatfishDirectTargetFields } from "./batfish-direct-target-fields";

const ROUTE_EMPTY_KEY = "route_empty_to_devices";
const EMPTY_MATCH_MODE_KEY = "empty_match_mode";
const DEFAULT_EMPTY_MATCH_MODE = "any";

const EMPTY_MATCH_MODES = ["any", "all"] as const;

export function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function parsePropertiesList(properties: string): string[] {
  return properties
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

/**
 * Shared field block for the Batfish "property lookup" steps (Batfish Node
 * Properties / Batfish Interface Properties): nodes/properties inputs (with
 * click-to-add suggestions), the route_empty_to_devices/empty_match_mode
 * audit toggle, output_key, and the BatfishDirectTargetFields block. Each
 * step's own copy differs only in wording and its (optional) extra field --
 * see workflow_steps/common/batfish_properties.py on the backend for the
 * matching consolidation of the executor logic.
 */
export interface BatfishPropertiesFieldsProps {
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  suggestionKeys: readonly string[];
  nodesHelpText: ReactNode;
  emptyHelpText: ReactNode;
  matchModeHelpNoun: string;
  outputKeyDefault: string;
  extraFields?: ReactNode;
}

export function BatfishPropertiesFields({
  config,
  onChange,
  suggestionKeys,
  nodesHelpText,
  emptyHelpText,
  matchModeHelpNoun,
  outputKeyDefault,
  extraFields,
}: BatfishPropertiesFieldsProps) {
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
    <>
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
        <p className="text-[11px] leading-4 text-muted-foreground">{nodesHelpText}</p>
      </div>

      {extraFields}

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
          {suggestionKeys.map((property) => (
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
        <p className="text-[11px] leading-4 text-muted-foreground">{emptyHelpText}</p>

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
              (default) routes a {matchModeHelpNoun} if at least one requested property is
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
          placeholder={outputKeyDefault}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          The result — a JSON artifact plus a row count — is stored under{" "}
          this key in the run&apos;s metadata (not per-device).
        </p>
      </div>

      <BatfishDirectTargetFields config={config} onChange={onChange} />
    </>
  );
}

"use client";

import { useCallback, useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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

import { ParseCiscoConfigHelpPanel } from "./help-panel";

const CONFIG_SOURCE_OPTIONS = [
  { value: "both", label: "Running and startup" },
  { value: "running", label: "Running only" },
  { value: "startup", label: "Startup only" },
] as const;

type ConfigSource = (typeof CONFIG_SOURCE_OPTIONS)[number]["value"];

function parseConfigSource(config: Record<string, unknown>): ConfigSource {
  const raw = config.config_source;
  if (typeof raw !== "string") return "both";
  return CONFIG_SOURCE_OPTIONS.some((option) => option.value === raw)
    ? (raw as ConfigSource)
    : "both";
}

function parseOutputKey(config: Record<string, unknown>): string {
  return typeof config.output_key === "string" ? config.output_key : "";
}

function ParseCiscoConfigConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const configSource = useMemo(() => parseConfigSource(config), [config]);
  const outputKey = parseOutputKey(config);

  const handleSourceChange = useCallback(
    (value: string) => {
      onChange({ ...config, config_source: value });
    },
    [config, onChange],
  );

  const handleOutputKeyChange = useCallback(
    (value: string) => {
      onChange({ ...config, output_key: value });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">config_source</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Label className="sr-only" htmlFor="config-source">
          Config source
        </Label>
        <Select value={configSource} onValueChange={handleSourceChange}>
          <SelectTrigger id="config-source" className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CONFIG_SOURCE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
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
          onChange={(event) => handleOutputKeyChange(event.target.value)}
          placeholder="cisco_config"
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

export const ParseCiscoConfigPlugin: PluginUIComponent = {
  ConfigPanel: ParseCiscoConfigConfigPanel,
  HelpPanel: ParseCiscoConfigHelpPanel,
};

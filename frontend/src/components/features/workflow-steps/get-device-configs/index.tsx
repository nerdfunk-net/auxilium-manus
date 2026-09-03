"use client";

import { useCallback, useMemo } from "react";

import { Badge } from "@/components/ui/badge";
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
import { SshCredentialField } from "@/components/features/workflow-steps/shared/ssh-credential-field";
import { GetDeviceConfigsHelpPanel } from "./help-panel";

const CONFIG_FORMAT_OPTIONS = [
  { value: "both", label: "Running and startup" },
  { value: "running", label: "Running only" },
  { value: "startup", label: "Startup only" },
] as const;

type ConfigFormat = (typeof CONFIG_FORMAT_OPTIONS)[number]["value"];

function parseConfigFormat(config: Record<string, unknown>): ConfigFormat {
  const raw = config.config_format;
  if (typeof raw !== "string") return "both";
  return CONFIG_FORMAT_OPTIONS.some((option) => option.value === raw)
    ? (raw as ConfigFormat)
    : "both";
}

function GetDeviceConfigsConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const configFormat = useMemo(() => parseConfigFormat(config), [config]);

  const handleFormatChange = useCallback(
    (value: string) => {
      onChange({ ...config, config_format: value });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <SshCredentialField config={config} onChange={onChange} />

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">config_format</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Label className="sr-only" htmlFor="config-format">
          Configuration format
        </Label>
        <Select value={configFormat} onValueChange={handleFormatChange}>
          <SelectTrigger id="config-format" className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CONFIG_FORMAT_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

export const GetDeviceConfigsPlugin: PluginUIComponent = {
  ConfigPanel: GetDeviceConfigsConfigPanel,
  HelpPanel: GetDeviceConfigsHelpPanel,
};

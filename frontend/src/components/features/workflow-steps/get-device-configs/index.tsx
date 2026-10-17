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
import { DeployReadTimeoutFields } from "@/components/features/workflow-steps/deploy-rendered-template/deploy-fields";
import {
  RetryBackoffSecondsField,
  parseRetryBackoffSeconds,
} from "@/components/features/workflow-steps/shared/retry-backoff-fields";
import { GetDeviceConfigsHelpPanel } from "./help-panel";

const CONFIG_FORMAT_OPTIONS = [
  { value: "both", label: "Running and startup" },
  { value: "running", label: "Running only" },
  { value: "startup", label: "Startup only" },
] as const;

type ConfigFormat = (typeof CONFIG_FORMAT_OPTIONS)[number]["value"];

const DEFAULT_READ_TIMEOUT = 120;
const MIN_READ_TIMEOUT = 5;
const MAX_READ_TIMEOUT = 600;

function parseConfigFormat(config: Record<string, unknown>): ConfigFormat {
  const raw = config.config_format;
  if (typeof raw !== "string") return "both";
  return CONFIG_FORMAT_OPTIONS.some((option) => option.value === raw)
    ? (raw as ConfigFormat)
    : "both";
}

function parseReadTimeout(config: Record<string, unknown>): number {
  return typeof config.read_timeout === "number" && Number.isFinite(config.read_timeout)
    ? config.read_timeout
    : DEFAULT_READ_TIMEOUT;
}

function GetDeviceConfigsConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const configFormat = useMemo(() => parseConfigFormat(config), [config]);
  const readTimeout = useMemo(() => parseReadTimeout(config), [config]);
  const retryBackoffSeconds = useMemo(() => parseRetryBackoffSeconds(config), [config]);

  const handleFormatChange = useCallback(
    (value: string) => {
      onChange({ ...config, config_format: value });
    },
    [config, onChange],
  );

  const handleReadTimeoutChange = useCallback(
    (value: string) => {
      const parsed = Number.parseInt(value, 10);
      const clamped = Number.isFinite(parsed)
        ? Math.min(MAX_READ_TIMEOUT, Math.max(MIN_READ_TIMEOUT, parsed))
        : DEFAULT_READ_TIMEOUT;
      onChange({ ...config, read_timeout: clamped });
    },
    [config, onChange],
  );

  const handleRetryBackoffSecondsChange = useCallback(
    (next: number[]) => {
      onChange({ ...config, retry_backoff_seconds: next });
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

      <DeployReadTimeoutFields
        readTimeout={readTimeout}
        onReadTimeoutChange={handleReadTimeoutChange}
      />

      <RetryBackoffSecondsField
        retryBackoffSeconds={retryBackoffSeconds}
        onRetryBackoffSecondsChange={handleRetryBackoffSecondsChange}
      />
    </div>
  );
}

export const GetDeviceConfigsPlugin: PluginUIComponent = {
  ConfigPanel: GetDeviceConfigsConfigPanel,
  HelpPanel: GetDeviceConfigsHelpPanel,
};

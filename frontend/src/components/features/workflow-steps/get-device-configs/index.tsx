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
import { useCredentialsQuery } from "@/components/features/settings/credentials/hooks/use-credentials-query";

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

function GetDeviceConfigsConfigPanel({
  config,
  onChange,
}: PluginConfigPanelProps) {
  const { data, isLoading } = useCredentialsQuery();
  const sshCredentials = useMemo(
    () =>
      (data?.credentials ?? []).filter(
        (credential) => credential.type === "ssh" && credential.status !== "expired",
      ),
    [data?.credentials],
  );

  const credentialReference =
    typeof config.credential_reference === "string" ? config.credential_reference : "";
  const configFormat = useMemo(() => parseConfigFormat(config), [config]);

  const handleCredentialChange = useCallback(
    (value: string) => {
      onChange({ ...config, credential_reference: value });
    },
    [config, onChange],
  );

  const handleFormatChange = useCallback(
    (value: string) => {
      onChange({ ...config, config_format: value });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">credential_reference</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            credential_ref
          </Badge>
        </div>

        {isLoading ? (
          <p className="text-[11px] text-muted-foreground">Loading credentials…</p>
        ) : sshCredentials.length === 0 ? (
          <p className="text-[11px] text-amber-600">
            No SSH credentials in Settings → Credentials
          </p>
        ) : (
          <Select value={credentialReference} onValueChange={handleCredentialChange}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Select SSH credential" />
            </SelectTrigger>
            <SelectContent>
              {sshCredentials.map((credential) => (
                <SelectItem key={credential.id} value={credential.name}>
                  {credential.name} ({credential.username})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

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
};

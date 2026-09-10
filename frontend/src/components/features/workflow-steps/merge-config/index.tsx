"use client";

import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { SshCredentialField } from "@/components/features/workflow-steps/shared/ssh-credential-field";
import { DeployReadTimeoutFields } from "@/components/features/workflow-steps/deploy-rendered-template/deploy-fields";

import { MergeConfigHelpPanel } from "./help-panel";

const DEFAULT_READ_TIMEOUT = 60;
const MIN_READ_TIMEOUT = 5;
const MAX_READ_TIMEOUT = 600;

export function buildMergeConfigConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    credential_reference:
      typeof config.credential_reference === "string"
        ? config.credential_reference
        : "",
    credential_source:
      config.credential_source === "run_param" ? "run_param" : "fixed",
    credential_param:
      typeof config.credential_param === "string"
        ? config.credential_param
        : "",
    source_filename:
      typeof config.source_filename === "string" ? config.source_filename : "",
    network_driver_override:
      typeof config.network_driver_override === "string"
        ? config.network_driver_override
        : "",
    read_timeout:
      typeof config.read_timeout === "number" &&
      Number.isFinite(config.read_timeout)
        ? config.read_timeout
        : DEFAULT_READ_TIMEOUT,
    ...patch,
  };
}

function MergeConfigConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const sourceFilename =
    typeof config.source_filename === "string" ? config.source_filename : "";
  const networkDriverOverride =
    typeof config.network_driver_override === "string"
      ? config.network_driver_override
      : "";
  const readTimeout =
    typeof config.read_timeout === "number" &&
    Number.isFinite(config.read_timeout)
      ? config.read_timeout
      : DEFAULT_READ_TIMEOUT;

  const handleSourceFilenameChange = useCallback(
    (value: string) => {
      onChange(buildMergeConfigConfig(config, { source_filename: value }));
    },
    [config, onChange],
  );

  const handleDriverOverrideChange = useCallback(
    (value: string) => {
      onChange(
        buildMergeConfigConfig(config, { network_driver_override: value }),
      );
    },
    [config, onChange],
  );

  const handleReadTimeoutChange = useCallback(
    (value: string) => {
      const parsed = Number.parseInt(value, 10);
      const clamped = Number.isFinite(parsed)
        ? Math.min(MAX_READ_TIMEOUT, Math.max(MIN_READ_TIMEOUT, parsed))
        : DEFAULT_READ_TIMEOUT;
      onChange(buildMergeConfigConfig(config, { read_timeout: clamped }));
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <SshCredentialField config={config} onChange={onChange} />

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">source_filename</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={sourceFilename}
          onChange={(event) => handleSourceFilenameChange(event.target.value)}
          placeholder="flash:partial.cfg"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Path passed to{" "}
          <span className="font-mono">
            copy &lt;source_filename&gt; running-config
          </span>
          , device filesystem prefix included. Match what the upstream Upload
          Config step wrote.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">
            network_driver_override
          </span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={networkDriverOverride}
          onChange={(event) => handleDriverOverrideChange(event.target.value)}
          placeholder="cisco_ios (optional)"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Overrides each device&apos;s network driver for Netmiko in this step.
        </p>
      </div>

      <DeployReadTimeoutFields
        readTimeout={readTimeout}
        onReadTimeoutChange={handleReadTimeoutChange}
      />
    </div>
  );
}

export const MergeConfigPlugin: PluginUIComponent = {
  ConfigPanel: MergeConfigConfigPanel,
  HelpPanel: MergeConfigHelpPanel,
};

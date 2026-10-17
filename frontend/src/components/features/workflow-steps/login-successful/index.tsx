"use client";

import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { SshCredentialField } from "@/components/features/workflow-steps/shared/ssh-credential-field";
import { LoginSuccessfulHelpPanel } from "./help-panel";

function LoginSuccessfulConfigPanel({
  config,
  onChange,
}: PluginConfigPanelProps) {
  const networkDriverOverride =
    typeof config.network_driver_override === "string" ? config.network_driver_override : "";

  const handleDriverOverrideChange = useCallback(
    (value: string) => {
      onChange({ ...config, network_driver_override: value });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <SshCredentialField config={config} onChange={onChange} />

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">network_driver_override</span>
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
    </div>
  );
}

export const LoginSuccessfulPlugin: PluginUIComponent = {
  ConfigPanel: LoginSuccessfulConfigPanel,
  HelpPanel: LoginSuccessfulHelpPanel,
};

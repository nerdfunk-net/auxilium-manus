"use client";

import { useCallback, useMemo } from "react";

import { Badge } from "@/components/ui/badge";
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
import { useCredentialsQuery } from "@/components/features/settings/credentials/hooks/use-credentials-query";
import { LoginSuccessfulHelpPanel } from "./help-panel";

function LoginSuccessfulConfigPanel({
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
  const networkDriverOverride =
    typeof config.network_driver_override === "string" ? config.network_driver_override : "";

  const handleCredentialChange = useCallback(
    (value: string) => {
      onChange({ ...config, credential_reference: value });
    },
    [config, onChange],
  );

  const handleDriverOverrideChange = useCallback(
    (value: string) => {
      onChange({ ...config, network_driver_override: value });
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
        ) : sshCredentials.length === 0 && !credentialReference ? (
          <p className="text-[11px] text-warning-foreground">
            No SSH credentials in Settings → Credentials
          </p>
        ) : (
          <Select value={credentialReference} onValueChange={handleCredentialChange}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Select SSH credential" />
            </SelectTrigger>
            <SelectContent>
              {credentialReference &&
                !sshCredentials.some((credential) => credential.name === credentialReference) && (
                  <SelectItem value={credentialReference} disabled>
                    {credentialReference} (not accessible)
                  </SelectItem>
                )}
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

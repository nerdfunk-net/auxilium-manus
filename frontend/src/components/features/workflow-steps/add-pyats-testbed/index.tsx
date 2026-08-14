"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

import { PyATSSourceSelectDialog } from "../shared/pyats-source-select-dialog";
import { pyatsSourceIdFromConfig, PYATS_SOURCE_ID_KEY } from "../shared/pyats-source-config";
import { AddPyatsTestbedHelpPanel } from "./help-panel";

const CREDENTIAL_REFERENCE_KEY = "credential_reference";
const NETWORK_DRIVER_OVERRIDE_KEY = "network_driver_override";

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function AddPyatsTestbedConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const sourceId = useMemo(() => pyatsSourceIdFromConfig(config), [config]);
  const credentialReference = stringFromConfig(config, CREDENTIAL_REFERENCE_KEY);
  const networkDriverOverride = stringFromConfig(config, NETWORK_DRIVER_OVERRIDE_KEY);

  const [sourceOpen, setSourceOpen] = useState(false);

  const { data, isLoading } = useCredentialsQuery();
  const usableCredentials = useMemo(
    () =>
      (data?.credentials ?? []).filter(
        (credential) =>
          (credential.type === "ssh" || credential.type === "generic") &&
          credential.status !== "expired",
      ),
    [data?.credentials],
  );

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [PYATS_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handleCredentialChange = useCallback(
    (value: string) => {
      onChange({ ...config, [CREDENTIAL_REFERENCE_KEY]: value });
    },
    [config, onChange],
  );

  const handleDriverOverrideChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [NETWORK_DRIVER_OVERRIDE_KEY]: event.target.value });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{PYATS_SOURCE_ID_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            pyats
          </Badge>
        </div>

        {sourceId ? (
          <p className="font-mono text-[11px] text-muted-foreground">{sourceId}</p>
        ) : (
          <p className="text-[11px] text-warning-foreground">Not configured</p>
        )}

        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setSourceOpen(true)}
        >
          {sourceId ? "Edit Source" : "Configure Source"}
        </Button>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{CREDENTIAL_REFERENCE_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            credential_ref
          </Badge>
        </div>

        {isLoading ? (
          <p className="text-[11px] text-muted-foreground">Loading credentials…</p>
        ) : usableCredentials.length === 0 && !credentialReference ? (
          <p className="text-[11px] text-warning-foreground">
            No SSH/generic credentials in Settings → Credentials
          </p>
        ) : (
          <Select value={credentialReference} onValueChange={handleCredentialChange}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Select a credential" />
            </SelectTrigger>
            <SelectContent>
              {credentialReference &&
                !usableCredentials.some(
                  (credential) => credential.name === credentialReference,
                ) && (
                  <SelectItem value={credentialReference} disabled>
                    {credentialReference} (not accessible)
                  </SelectItem>
                )}
              {usableCredentials.map((credential) => (
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
          <span className="font-mono text-xs font-medium">{NETWORK_DRIVER_OVERRIDE_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={networkDriverOverride}
          onChange={handleDriverOverrideChange}
          placeholder="iosxe (optional)"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Overrides the resolved pyATS os for every device in this step.
        </p>
      </div>

      <PyATSSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />
    </div>
  );
}

export const AddPyatsTestbedPlugin: PluginUIComponent = {
  ConfigPanel: AddPyatsTestbedConfigPanel,
  HelpPanel: AddPyatsTestbedHelpPanel,
};

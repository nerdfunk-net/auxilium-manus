"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { useNautobotSourceCredentials } from "@/hooks/queries/use-nautobot-source-credentials";

import {
  NAUTOBOT_SOURCE_ID_KEY,
  isNautobotSourceConfigured,
  nautobotSourceIdFromConfig,
} from "../shared/nautobot-source-config";
import { NautobotSourceSelectDialog } from "../shared/nautobot-source-select-dialog";
import { UpdateDeviceDialog } from "./update-device-dialog";
import type { UpdateNautobotDeviceConfig } from "./types";
import { countEnabledUpdateFields } from "./update-device-config";
import { UpdateNautobotDeviceHelpPanel } from "./help-panel";

function UpdateNautobotDeviceConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });
  const updateConfig = config as UpdateNautobotDeviceConfig;

  const [sourceOpen, setSourceOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);

  const enabledFieldCount = useMemo(() => countEnabledUpdateFields(config), [config]);
  const interfaceCount = Array.isArray(config.interfaces) ? config.interfaces.length : 0;
  const identifierMode =
    (updateConfig.device_identifier?.mode as string | undefined) ?? "from_context";

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { inventory_source, ...rest } = config;
      onChange({ ...rest, [NAUTOBOT_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handleDialogSave = useCallback(
    (next: UpdateNautobotDeviceConfig) => {
      onChange({
        ...config,
        ...next,
        [NAUTOBOT_SOURCE_ID_KEY]: sourceId,
      });
    },
    [config, onChange, sourceId],
  );

  const isSourceConfigured = isNautobotSourceConfigured(config);
  const hasUpdatePayload = enabledFieldCount > 0 || interfaceCount > 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{NAUTOBOT_SOURCE_ID_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            nautobot
          </Badge>
        </div>

        {isSourceConfigured ? (
          <p className="font-mono text-[11px] text-muted-foreground">
            {sourceId}
            {credentials.isReady ? (
              <span className="block truncate font-sans text-muted-foreground">
                {credentials.url}
              </span>
            ) : credentials.isLoading ? (
              <span className="block font-sans">Loading credentials…</span>
            ) : (
              <span className="block font-sans text-amber-600">
                Source not found in settings
              </span>
            )}
          </p>
        ) : (
          <p className="text-[11px] text-amber-600">Not configured</p>
        )}

        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setSourceOpen(true)}
        >
          {isSourceConfigured ? "Edit Source" : "Configure Source"}
        </Button>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">update_payload</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            object
          </Badge>
        </div>

        {hasUpdatePayload ? (
          <p className="text-[11px] text-muted-foreground">
            {enabledFieldCount} enabled field{enabledFieldCount === 1 ? "" : "s"},{" "}
            {interfaceCount} interface{interfaceCount === 1 ? "" : "s"},{" "}
            {identifierMode === "explicit" ? "explicit device" : "from context"}
          </p>
        ) : (
          <p className="text-[11px] text-amber-600">No enabled update fields configured</p>
        )}

        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setDialogOpen(true)}
        >
          Edit Update
        </Button>
      </div>

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />

      <UpdateDeviceDialog
        open={dialogOpen}
        value={updateConfig}
        onClose={() => setDialogOpen(false)}
        onChange={handleDialogSave}
      />
    </div>
  );
}

export const UpdateNautobotDevicePlugin: PluginUIComponent = {
  ConfigPanel: UpdateNautobotDeviceConfigPanel,
  HelpPanel: UpdateNautobotDeviceHelpPanel,
};

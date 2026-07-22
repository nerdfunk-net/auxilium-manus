"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
import { AddToNautobotDialog } from "./add-to-nautobot-dialog";
import {
  countConfiguredRequiredFields,
  countEnabledOptionalFields,
  parseDeviceFieldsConfig,
} from "./add-to-nautobot-config";
import type { AddToNautobotConfig, DeviceFieldsConfig } from "./types";
import { AddToNautobotHelpPanel } from "./help-panel";

// Mirrors backend/workflow_steps/add_to_nautobot/config.py::get_config() — this is
// the actual seed applied to a fresh node (the backend get-config endpoint has no
// frontend caller, so it does not seed new nodes on its own).
const DEFAULT_DEVICE_FIELDS: DeviceFieldsConfig = {
  name: { enabled: true, value: "{parsed.cisco_config.hostname}" },
  role: { enabled: true, value: "{nautobot.origin}" },
  status: { enabled: true, value: "{nautobot.origin | default('Active')}" },
  location: { enabled: true, value: "{nautobot.origin}" },
  device_type: { enabled: true, value: "{nautobot.origin}" },
};

function AddToNautobotConfigPanel({ config, onChange, nodeId }: PluginConfigPanelProps) {
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });
  const addConfig = config as AddToNautobotConfig;

  const [sourceOpen, setSourceOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);

  const initializedForNode = useRef<string | null>(null);
  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!addConfig.device_fields || typeof addConfig.device_fields !== "object") {
      onChange({ ...config, device_fields: DEFAULT_DEVICE_FIELDS });
    }
  }, [nodeId, config, addConfig.device_fields, onChange]);

  const deviceFields = useMemo(
    () => parseDeviceFieldsConfig(addConfig.device_fields),
    [addConfig.device_fields],
  );
  const requiredCount = countConfiguredRequiredFields(deviceFields);
  const optionalCount = countEnabledOptionalFields(deviceFields);
  const interfaceCount = Array.isArray(addConfig.interfaces) ? addConfig.interfaces.length : 0;

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [NAUTOBOT_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const handleDialogSave = useCallback(
    (next: AddToNautobotConfig) => {
      onChange({ ...config, ...next, [NAUTOBOT_SOURCE_ID_KEY]: sourceId });
    },
    [config, onChange, sourceId],
  );

  const isSourceConfigured = isNautobotSourceConfigured(config);

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
              <span className="block font-sans text-amber-600">Source not found in settings</span>
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
          <span className="font-mono text-xs font-medium">device_fields</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            object
          </Badge>
        </div>

        {requiredCount === 5 ? (
          <p className="text-[11px] text-muted-foreground">
            5 required fields set, {optionalCount} optional, {interfaceCount} interface
            {interfaceCount === 1 ? "" : "s"}
          </p>
        ) : (
          <p className="text-[11px] text-amber-600">
            {requiredCount}/5 required fields set
          </p>
        )}

        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setDialogOpen(true)}
        >
          Edit Device
        </Button>
      </div>

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />

      <AddToNautobotDialog
        open={dialogOpen}
        value={addConfig}
        onClose={() => setDialogOpen(false)}
        onChange={handleDialogSave}
      />
    </div>
  );
}

export const AddToNautobotPlugin: PluginUIComponent = {
  ConfigPanel: AddToNautobotConfigPanel,
  HelpPanel: AddToNautobotHelpPanel,
};

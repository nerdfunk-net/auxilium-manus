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
import { NautobotSourceStatus, SourceRow } from "../shared/source-row";

// Mirrors backend/workflow_steps/add_to_nautobot/config.py::get_config(): what the panel shows
// (and the executor uses) while the node has no saved device_fields.
const DEFAULT_DEVICE_FIELDS: DeviceFieldsConfig = {
  name: { enabled: true, value: "{parsed.cisco_config.running.hostname}" },
  role: { enabled: true, value: "{nautobot.origin}" },
  status: { enabled: true, value: "{nautobot.origin | default('Active')}" },
  location: { enabled: true, value: "{nautobot.origin}" },
  device_type: { enabled: true, value: "{nautobot.origin}" },
  platform: { enabled: true, value: "{nautobot.origin}" },
  secrets_group: { enabled: true, value: "{nautobot.origin}" },
  software_version: { enabled: true, value: "{nautobot.origin}" },
  serial: { enabled: true, value: "{nautobot.origin}" },
  asset_tag: { enabled: true, value: "{nautobot.origin}" },
  tags: { enabled: true, value: "{nautobot.origin}" },
};

function AddToNautobotConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });
  const addConfig = useMemo(
    () =>
      ({
        ...config,
        device_fields: config.device_fields ?? DEFAULT_DEVICE_FIELDS,
      }) as AddToNautobotConfig,
    [config],
  );

  const [sourceOpen, setSourceOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);


  const deviceFields = useMemo(
    () => parseDeviceFieldsConfig(addConfig.device_fields),
    [addConfig.device_fields],
  );
  const requiredCount = countConfiguredRequiredFields(deviceFields);
  const optionalCount = countEnabledOptionalFields(deviceFields);
  const interfaceCount = Array.isArray(addConfig.interfaces) ? addConfig.interfaces.length : 0;
  const interfacesSource = addConfig.interfaces_source ?? "manual";
  const customFieldsSource = addConfig.custom_fields_source ?? "manual";

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


  return (
    <div className="flex flex-col gap-4">
      <SourceRow
        label={NAUTOBOT_SOURCE_ID_KEY}
        badge="nautobot"
        sourceId={sourceId}
        onOpen={() => setSourceOpen(true)}
        status={
          <NautobotSourceStatus
            isReady={credentials.isReady}
            isLoading={credentials.isLoading}
            url={credentials.url}
          />
        }
      />

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">device_fields</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            object
          </Badge>
        </div>

        {requiredCount === 5 ? (
          <p className="text-[11px] text-muted-foreground">
            5 required fields set, {optionalCount} optional,{" "}
            {interfacesSource === "nautobot_origin"
              ? "all interfaces from Nautobot origin"
              : `${interfaceCount} interface${interfaceCount === 1 ? "" : "s"}`}
            {interfacesSource === "nautobot_origin"
              ? addConfig.redundancy_groups?.enabled === true
                ? ", HSRP/VRRP groups on"
                : ", HSRP/VRRP groups off"
              : ""}
            {customFieldsSource === "nautobot_origin" ? ", all custom fields from Nautobot origin" : ""}
          </p>
        ) : (
          <p className="text-[11px] text-warning-foreground">
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

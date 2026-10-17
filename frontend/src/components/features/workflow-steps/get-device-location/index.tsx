"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { GetDeviceLocationHelpPanel } from "./help-panel";
import { LocationTypeSelectDialog } from "./location-type-select-dialog";

const LOCATION_TYPE_KEY = "location_type";
const TARGET_ATTRIBUTE_KEY = "target_attribute";
const CASE_INSENSITIVE_KEY = "case_insensitive_lookup";
const DEFAULT_TARGET = "custom.location";

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const value = config[key];
  return typeof value === "string" ? value : "";
}

function GetDeviceLocationConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const sourceId = useMemo(() => nautobotSourceIdFromConfig(config), [config]);
  const credentials = useNautobotSourceCredentials({ sourceId });
  const locationType = stringFromConfig(config, LOCATION_TYPE_KEY);
  const target = stringFromConfig(config, TARGET_ATTRIBUTE_KEY);
  const caseInsensitive = config[CASE_INSENSITIVE_KEY] === true;
  const isSourceConfigured = isNautobotSourceConfigured(config);

  const [sourceOpen, setSourceOpen] = useState(false);
  const [typeOpen, setTypeOpen] = useState(false);

  const handleSourceChange = useCallback(
    (newSourceId: string) => {
      // A different source has different location types.
      onChange({
        ...config,
        [NAUTOBOT_SOURCE_ID_KEY]: newSourceId,
        ...(newSourceId !== sourceId ? { [LOCATION_TYPE_KEY]: "" } : {}),
      });
    },
    [config, onChange, sourceId],
  );

  const handleTypeChange = useCallback(
    (newType: string) => onChange({ ...config, [LOCATION_TYPE_KEY]: newType }),
    [config, onChange],
  );

  const handleTargetChange = useCallback(
    (value: string) => onChange({ ...config, [TARGET_ATTRIBUTE_KEY]: value }),
    [config, onChange],
  );

  const handleCaseInsensitive = useCallback(
    (checked: boolean) => onChange({ ...config, [CASE_INSENSITIVE_KEY]: checked }),
    [config, onChange],
  );

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
              <span className="block font-sans text-warning-foreground">
                Source not found in settings
              </span>
            )}
          </p>
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
          {isSourceConfigured ? "Edit Source" : "Configure Source"}
        </Button>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{LOCATION_TYPE_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        {locationType ? (
          <p className="truncate text-[11px] text-muted-foreground">{locationType}</p>
        ) : (
          <p className="text-[11px] text-warning-foreground">Not configured</p>
        )}
        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          disabled={!isSourceConfigured}
          onClick={() => setTypeOpen(true)}
        >
          Select Location Type
        </Button>
        {!isSourceConfigured ? (
          <p className="text-[11px] text-muted-foreground">
            Configure a source first to list its location types.
          </p>
        ) : null}
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{TARGET_ATTRIBUTE_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <input
          aria-label="Target attribute"
          className="h-9 w-full rounded-lg border border-input bg-card px-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-step/40"
          placeholder={DEFAULT_TARGET}
          value={target}
          onChange={(event) => handleTargetChange(event.target.value)}
        />
        <p className="text-[11px] text-muted-foreground">
          Receives the location name. Empty uses{" "}
          <span className="font-mono">{DEFAULT_TARGET}</span>.
        </p>
      </div>

      <div className="space-y-1.5 border-t pt-3">
        <label className="flex items-center gap-1.5 text-xs font-medium">
          <Checkbox
            checked={caseInsensitive}
            onCheckedChange={(checked) => handleCaseInsensitive(checked === true)}
          />
          Use case-insensitive lookup
        </label>
        <p className="text-[11px] leading-4 text-muted-foreground">
          When the device has no Nautobot ID yet, match its name regardless of case.
        </p>
      </div>

      <NautobotSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceChange}
      />
      <LocationTypeSelectDialog
        open={typeOpen}
        sourceId={sourceId}
        selectedType={locationType}
        onClose={() => setTypeOpen(false)}
        onSave={handleTypeChange}
      />
    </div>
  );
}

export const GetDeviceLocationPlugin: PluginUIComponent = {
  ConfigPanel: GetDeviceLocationConfigPanel,
  HelpPanel: GetDeviceLocationHelpPanel,
};

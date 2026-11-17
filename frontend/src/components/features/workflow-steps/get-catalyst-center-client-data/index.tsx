"use client";

import { useCallback } from "react";

import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { Input } from "@/components/ui/input";

import { CheckboxField } from "../shared/checkbox-field";
import { FieldHeader } from "../shared/field-header";
import {
  clampLookbackHours,
  MAX_LOOKBACK_HOURS,
  MIN_LOOKBACK_HOURS,
  readLookbackHours,
} from "./config";
import { GetCatalystCenterClientDataHelpPanel } from "./help-panel";

function GetCatalystCenterClientDataConfigPanel({
  config,
  onChange,
}: PluginConfigPanelProps) {
  const lookbackHours = readLookbackHours(config);
  const dryRun = config.dry_run === true;

  const patchConfig = useCallback(
    (patch: Record<string, unknown>) => onChange({ ...config, ...patch }),
    [config, onChange],
  );

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <FieldHeader name="lookback_hours" type="integer" />
        <Input
          type="number"
          min={MIN_LOOKBACK_HOURS}
          max={MAX_LOOKBACK_HOURS}
          value={lookbackHours}
          onChange={(event) =>
            patchConfig({ lookback_hours: clampLookbackHours(event.target.value) })
          }
          className="h-8 font-mono text-xs focus-visible:ring-step/40"
        />
        <p className="text-[11px] text-muted-foreground">
          Hours back in which Catalyst Center saw the wired clients.
        </p>
      </div>

      <CheckboxField
        id="get-catalyst-center-client-data-dry-run"
        label="dry_run"
        checked={dryRun}
        onCheckedChange={(checked) => patchConfig({ dry_run: checked })}
      />
    </div>
  );
}

export const GetCatalystCenterClientDataPlugin: PluginUIComponent = {
  ConfigPanel: GetCatalystCenterClientDataConfigPanel,
  HelpPanel: GetCatalystCenterClientDataHelpPanel,
};

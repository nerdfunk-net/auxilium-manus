"use client";

import { useCallback } from "react";

import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { CheckboxField } from "@/components/features/workflow-steps/shared/checkbox-field";
import { FieldHeader } from "@/components/features/workflow-steps/shared/field-header";
import { GitSourceConfigPanel } from "@/components/features/workflow-steps/shared/git-source-config-panel";

import { GetAgeOfBackupHelpPanel } from "./help-panel";

const DEFAULT_PATH_TEMPLATE = "{device.name}.cfg";
const DEFAULT_OUTPUT_BAG = "backup_age";

const PATH_PLACEHOLDERS = [
  "{device.name}",
  "{device.hostname}",
  "{device.primary_ip4}",
  "{nautobot.location.name}",
  "{nautobot.role.name}",
  "{nautobot.custom_fields.<slug>}",
];

function text(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

function buildGetAgeOfBackupConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    git_repository_id: typeof config.git_repository_id === "number" ? config.git_repository_id : null,
    allow_stale_repository: config.allow_stale_repository === true,
    path_template: text(config.path_template, DEFAULT_PATH_TEMPLATE),
    output_bag: text(config.output_bag, DEFAULT_OUTPUT_BAG),
    use_marker: config.use_marker === true,
    marker_storage_key: text(config.marker_storage_key, ""),
    ...patch,
  };
}

function GetAgeOfBackupConfigPanel(props: PluginConfigPanelProps) {
  const { config, onChange } = props;

  const pathTemplate = text(config.path_template, DEFAULT_PATH_TEMPLATE);
  const outputBag = text(config.output_bag, DEFAULT_OUTPUT_BAG);
  const useMarker = config.use_marker === true;
  const markerStorageKey = text(config.marker_storage_key, "");

  const patchConfig = useCallback(
    (patch: Record<string, unknown>) => onChange(buildGetAgeOfBackupConfig(config, patch)),
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <GitSourceConfigPanel
        {...props}
        description="The repository that holds the device config backups (Settings → Git Repositories)."
        showAllowStaleToggle
      />

      <div className="space-y-1.5">
        <FieldHeader name="path_template" type="string" />
        <Input
          value={pathTemplate}
          onChange={(event) => patchConfig({ path_template: event.target.value })}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Where the backup file of each device lives. Placeholders: {PATH_PLACEHOLDERS.join(", ")}.
          Use the template of the backup workflow, e.g.{" "}
          <span className="font-mono">{"{nautobot.location.name}/{device.name}.cfg"}</span>.
        </p>
      </div>

      <div className="space-y-1.5">
        <FieldHeader name="output_bag" type="string" />
        <Input
          value={outputBag}
          onChange={(event) => patchConfig({ output_bag: event.target.value })}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Attribute bag that receives the result, e.g.{" "}
          <span className="font-mono">{`{${outputBag || DEFAULT_OUTPUT_BAG}.age_days}`}</span>.
        </p>
      </div>

      <CheckboxField
        id="get-age-of-backup-use-marker"
        label="use_marker"
        checked={useMarker}
        onCheckedChange={(checked) => patchConfig({ use_marker: checked })}
        description="Also read when the backup was last checked, from a record a Store in DB step wrote after the backup (a git commit exists only when the config changed)."
      />

      {useMarker ? (
        <div className="space-y-1.5 pl-1">
          <FieldHeader name="marker_storage_key" type="string" />
          <Input
            value={markerStorageKey}
            onChange={(event) => patchConfig({ marker_storage_key: event.target.value })}
            placeholder="backup_checked"
            className="h-8 font-mono text-xs"
          />
          {markerStorageKey.trim() === "" ? (
            <p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
              Enter the storage key the Store in DB step uses; the step cannot run without it.
            </p>
          ) : (
            <p className="text-[11px] text-muted-foreground">
              Same key as in the Store in DB step. Placeholders such as{" "}
              <span className="font-mono">{"{nautobot.location.name}"}</span> are rendered per
              device.
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}

export const GetAgeOfBackupPlugin: PluginUIComponent = {
  ConfigPanel: GetAgeOfBackupConfigPanel,
  HelpPanel: GetAgeOfBackupHelpPanel,
};
